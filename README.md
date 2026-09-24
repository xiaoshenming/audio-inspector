# DEV-PB2

面向 BatchOps 最终带配音视频的独立审查与重配音模块。输入同一版本的 MP4、配音源码、可选字幕及题目，输出可跳转的疑点、原文与建议新文。管理员可选择放行或改写建议；模块按批准文字重新配音并生成完整视频，再次检查并等待管理员确认。模块不修改 BatchOps 任务，不发送客户视频。

**推荐入口是 `dev-pb2-cycle`。** [交接清单](docs/module-handoff.md)讲如何运行；[对外协议](docs/batchops-integration.md)讲字段与状态；[BatchOps 接入教程](docs/batchops-adapter-guide.md)给出真实接点、资源映射及改文后如何创建新权威版本。[工程基线审查](docs/code-review-baseline-20260924.md)记录本轮修复、验证和剩余边界。

## 运行

需要 Python 3.11+、FFmpeg/ffprobe、`faster-whisper` small 模型。`local` 局部重配音还要求 FFmpeg 带 `libass` 的 `subtitles` 滤镜；可用 `ffmpeg -hide_banner -filters | rg ' subtitles '` 预检，缺少该滤镜时选择具备此能力的构建或使用 `worker` 模式。Qwen ASR、DeepSeek 和本地重配音 TTS 的密钥/端点从环境变量读取；字段名见 `.env.example`。worker 完整渲染路线另需 `.[batchops]` 与隔离 Render 子节点参数。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
# 在 .env 中填写 DASHSCOPE_API_KEY 和 DEEPSEEK_API_KEY；endpoint 已有 B2B 当前值。
set -a
source .env
set +a
dev-pb2-cycle start --request request.json --session /private/pb2/session-1 \
  --work-root /private/pb2/work --source-pack /private/source.tar \
  --unburned /private/unburned.mp4 --repair-mode local
dev-pb2-cycle status --session /private/pb2/session-1
```

`DASHSCOPE_ASR_ENDPOINT` 是 Qwen 语音转文字的请求地址，`DASHSCOPE_TTS_ENDPOINT` 是 Qwen 文字转语音的请求地址。两者的 **B2B 当前值已填入 `.env.example`**，同事无需另找 URL。`DASHSCOPE_API_KEY` 是鉴权密钥，仍由服务器受限配置或团队的安全渠道提供。若在新的阿里云工作空间运行，应使用该工作空间对应的 endpoint。

`request.json` 最小形状：

```json
{
  "item_id": "batchops-item-123",
  "revision_id": "final-tts-r1",
  "video_path": "/private/final.mp4",
  "source_path": "/private/main.py",
  "subtitle_path": "/private/final.srt",
  "tts_profile": {"provider": "qwen_audio", "model": "qwen-audio-3.0-tts-plus", "voice": "longanlufeng", "speech_rate": 0.9},
  "question": {"question": "已知……，求……"}
}
```

生产调用还应提供视频、源码、字幕 SHA，模块会核对实际文件。要修复还需要与源码同版的完整源码包；`local` 模式需要未烧字幕原片和可定位的字幕时间窗。完整 `worker` 渲染需另传原片 `render_profile`，字段见[对外协议](docs/batchops-integration.md#输入合同)。资源只给本地受控路径，不把签名 URL 或密钥写入请求。

## 决定与循环

| `phase` | 含义 |
|---|---|
| `release_ready` | 首轮检查干净，或管理员已明确放行；接入方核对 revision 与视频 SHA 后沿原有交付路径继续 |
| `awaiting_admin` | 有疑点，或修复后的新成片已复查；显示视频位置和可编辑的新文，等待管理员 |
| `repairing` | 已保存批准的修改，正在配音和复查；中断后用 `resume` 续跑同一决定 |
| `inspection_failed` | 检查证据未完成；运行 `retry` 或交管理员处理，不当作没问题 |

```bash
# 候选需要管理员决定；edits.json 为 [{"issue_id":"...","new_text":"..."}]
dev-pb2-cycle decide --session /private/pb2/session-1 \
  --actor admin-42 --action approve_repair --edits edits.json
# 修复后即使机器复查干净，仍需管理员再确认；也可以再次改文
dev-pb2-cycle decide --session /private/pb2/session-1 \
  --actor admin-42 --action accept_as_is
dev-pb2-cycle retry --session /private/pb2/session-1
dev-pb2-cycle resume --session /private/pb2/session-1
```

筛查运行 Qwen ASR、DeepSeek 源码与音频语义审查，以及函数记号被机械念出括号的定向听写。初轮 `clean` 可原路放行；机器结果仅表示当前检查未提出候选，不能代表绝对无误。真实样本的人工循环记录见[单条闭环](docs/real-152-closure.md)；批量试验及独立漏检审计见[65 条报告](docs/real-65-closure.md)和[可靠性审计](docs/independent-reliability-audit.md)。

`dev-pb2 inspect`、`dev-pb2 decide`、`dev-pb2-close-loop`、批量评测等命令仍可用于开发和研究；它们不是推荐的正式集成入口。开发检查：`python -m pytest && python -m ruff check src tests && python -m compileall -q src tests`。
