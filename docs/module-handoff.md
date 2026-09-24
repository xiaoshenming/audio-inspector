# DEV-PB2 交接清单

## 从这里开始

1. 阅读 [BatchOps 接入教程](batchops-adapter-guide.md) 和 [对外协议](batchops-integration.md)。正式接入只推荐 `dev-pb2-cycle`；底层 `inspect/decide/rebuild/worker-render` 是调试或实验入口。
2. 安装 Python 3.11+、FFmpeg/ffprobe。筛查需 `faster-whisper` 的 `small` 模型、Qwen ASR 与 DeepSeek；本地重配音还需 TTS 端点及 FFmpeg 的 `subtitles` 滤镜（libass）。运行 `ffmpeg -hide_banner -filters | rg ' subtitles '` 预检；某些本机 FFmpeg 构建缺此滤镜，需换用具备它的构建或选 `worker` 模式。**B2B 当前 ASR/TTS endpoint 的完整地址已在 `.env.example`**；只需从受限环境配置实际 API Key，不把密钥放入仓库或交接包。
3. 按[输入合同](batchops-integration.md#输入合同)准备同一最终 TTS revision 的 MP4、实际配音源码、可选 SRT、题目、文件 SHA；要执行修复时再准备实际 TTS 参数、完整源码包及 `local` 模式的未烧字幕原片。`worker` 模式还需原渲染规格，不猜默认音色或画幅。
4. 运行 `dev-pb2-cycle start/status/decide/retry/resume`。首轮 `clean` 输出 `release_ready`；候选等管理员；批准改文后进入 `repairing`，模块生成新成片并复查，每轮再次等管理员确认。中断或报错时 `resume` 续跑同一决定。模块不实际向客户发送。

## 可直接运行的最短流程

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[batchops]'
dev-pb2-cycle start --request request.json --session /private/pb2/session-1 \
  --work-root /private/pb2/work --source-pack source.tar \
  --unburned unburned.mp4 --repair-mode local
dev-pb2-cycle status --session /private/pb2/session-1
dev-pb2-cycle decide --session /private/pb2/session-1 \
  --actor reviewer-42 --action approve_repair --edits edits.json
dev-pb2-cycle decide --session /private/pb2/session-1 \
  --actor reviewer-42 --action accept_as_is
```

命令中的管理员动作只在 `phase=awaiting_admin` 时使用。`edits.json` 可为 `[{"issue_id":"...","new_text":"管理员确认的新文"}]`；具体字段、失败重试和 worker 模式见[协议](batchops-integration.md)。如果只在本机试用 local 路线，`pip install -e .` 即可；额外的 `.[batchops]` 仅为隔离子节点适配器提供 TOS 依赖。

## 交接包应该包含

| 内容 | 用途 |
|---|---|
| 完整源码、`pyproject.toml`、`README.md`、`.env.example`、`tests/`、`docs/` | 安装、运行、审查与接线 |
| `DEV-PB2` 的 Git 基线与历史包 | 恢复精确版本、比较后续变更；以交接时的提交 SHA 和压缩包 SHA 为准 |
| 冻结的文本样本与结果 `benchmarks/` | 回归核查筛查行为 |
| 可选的独立媒体样本包 | 离线复验；真实客户媒体不得放入公开 Git 或无权限归档 |

仓库中的 `benchmarks/2026-09-23/` 保存 600 条合成样本的文本标签、冻结结果和诊断重算；媒体按[样本交接](sample-handoff.md)单独保存。真实样本闭环见[单条回执](real-152-closure.md)和[65 条批测](real-65-closure.md)。65 条批测使用机器建议模拟文字确认，不能当成员工人工认可率；独立审计说明了机器漏检边界，见[可靠性记录](independent-reliability-audit.md)。

## 同事接线时的关键区别

- BatchOps 管理台最终按钮在 `apps/batchops/control/components/admin/production-stage-panel.tsx`，客户放行仍由原权限接口执行。DEV-PB2 的 `release_ready` 是文件绑定的交付建议，不是发送动作。
- 当前 BatchOps 的 `tts-completion/rerender` 只有 `reason`，会复用已锁定源码，**不会应用管理员批准的改文**。同事需新增新权威内容 revision / 源码包与正式 TTS 的适配编排；教程列出了字段映射和接线顺序。
- TTS completion 列表只暴露视频 URL 等摘要；同事须关联权威内容版本、源码归档、字幕和最终 render 尝试，不能把旧源码/旧字幕与新 MP4 混用。
- 局部重配音适用于字幕时间窗唯一、未烧字幕原片可用且新旧语速接近的情况；其他情况走完整 Render 子节点。修复失败时保留旧可播放视频和原因，交由管理员处理。

本仓库未修改 BatchOps 的前端、数据库、正式任务状态或客户释放动作。所有生产环境接线和权限测试应在 BatchOps 自身仓库完成。

收到离线交接包后，先在解压目录执行 `shasum -a 256 -c SHA256SUMS`，再阅读包根目录的 `HANDOFF.txt`。要恢复有完整提交历史的仓库，使用 `git clone --branch DEV-PB2 git/history.bundle dev-pb2-restored`；直接使用源码则进入 `source/`。`git clone` 不指定 `--branch` 时，部分 Git 版本无法从 bundle 自动推断默认分支。
