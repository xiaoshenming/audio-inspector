# DEV-PB2

面向 BatchOps 最终带配音视频的独立旁白审查模块。它接收最终 MP4、实际配音所用源码、可选字幕和题目上下文，输出可定位的疑点、简短的“原文 → 建议新文”与稳定的机器合同。模块不修改 BatchOps 状态，也不自动拒绝交付。

## 交付前的三种结果

| `status` | 含义 | 给 BatchOps 的信号 |
|---|---|---|
| `clean` | 所有审查步骤完成，未发现候选 | `can_continue=true`，沿原有交付流程继续 |
| `candidate` | 找到值得核听的疑点 | `needs_admin_review=true`，显示时间点和文字对照 |
| `failed_open` | 请求失败或证据不完整 | 告知管理员“尚未完成筛查”，不能显示成“没问题” |

对候选，管理员可以选择“没问题，继续交付”或“确认修复并重做”；第二种操作允许逐条修改建议新文。模块只输出带版本与 SHA 的确定性 `voiceover_overrides` 和 `rebuild_final_video` 命令。真正的 TTS 请求、视频重合成、重新审查以及最终发送仍由 BatchOps 编排。AI 只提出疑点和文字建议，不能擅自确认修复或释放给客户。

## 安装和运行

需要 Python 3.11+、FFmpeg/ffprobe；函数记号字面读法补查需要 faster-whisper small 模型。密钥和 ASR 端点从环境变量读取。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export DASHSCOPE_API_KEY=...
export DASHSCOPE_ASR_ENDPOINT=...
export DEEPSEEK_API_KEY=...
dev-pb2 inspect --request request.json --work-root /private/dev-pb2-runs
```

`request.json` 示例（文件应是最终确认的同一版本）：

```json
{
  "item_id": "batchops-item-123",
  "revision_id": "R2",
  "video_path": "/private/final.mp4",
  "source_path": "/private/final.py",
  "subtitle_path": "/private/final.srt",
  "question": {"question": "已知……，求……"}
}
```

生产调用还应提供 `video_sha256` 和 `source_sha256`，模块会核对实际文件。结果写在 `work-root/<输入指纹>/inspection.json`；命令也在标准输出打印 JSON。复用同样输入会复用已完成的阶段证据。`issues` 包含问题类别、时间点、源码行、原文、ASR 听到的文字、建议新文和修复方式。没有字幕仍能运行，但源码问题可能没有精确时间点。

管理员决定示例：

```bash
dev-pb2 decide --inspection /private/run/inspection.json \
  --source /private/final.py --actor admin-42 \
  --action approve_repair --edits edits.json --output /private/repair-command.json
```

`edits.json` 为 `[ {"issue_id":"...", "new_text":"管理员最终指定的文字"} ]`。要放行则使用 `--action accept_as_is`，无需 `--edits`。修复命令会带原视频/源码 SHA、版本号、管理员、幂等键及逐行口播替换；源码版本变化或问题 ID 不匹配会拒绝生成过期命令。详见[BatchOps 接入合同](docs/batchops-integration.md)。

## 筛查内容与数据

筛查包含 Qwen ASR 听写、DeepSeek 源码旁白审查、源码与 ASR 差异审查，以及针对 `f(x)` 被念出“左括号……右括号”的定向逐字听写。多音字旧链路已从此分支移除。[筛查流程](docs/screening-workflow.md)保留每一阶段的独立运行命令。

本分支继承此前全部 Git 提交历史，同时在本地 `input/synthetic-tts-20260923/` 与 `input/synthetic-tts-challenge-20260923/` 保存 600 条合成样本及报告，合计约 846 MB。媒体和可能含内部路径的报告被 Git 忽略；交给同事时需**连同样本包单独传送**。结论和样本限制见[量化记录](docs/synthetic-benchmark.md)。

开发检查：`python -m pytest && python -m ruff check src tests && python -m compileall -q src tests`。
