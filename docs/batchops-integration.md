# DEV-PB2 对外协议

本文是模块与 BatchOps 的交界面说明；具体接线步骤见 [BatchOps 接入教程](batchops-adapter-guide.md)。推荐只调用 `dev-pb2-cycle`（或同名 Python `start/load/view/apply/retry_inspection/resume_repair` 函数）。`dev-pb2 inspect`、`decide`、`rebuild` 是底层调试入口，不应由正式接入方自行拼接成另一套流程。

## 边界与状态

模块读取同一最终配音版本的 MP4、实际配音源码、字幕和题目，筛查后返回疑点与可修改的文字建议。它在独立会话目录保存检查、管理员决定、修复与复查证据；不会修改 BatchOps 数据库，也不会发送客户视频。

| `phase` | 含义 | 接入方动作 |
|---|---|---|
| `release_ready` | 初轮检查为 `clean`，或管理员明确选择放行 | 核对 `release.revision_id` 与 `release.video_sha256`，走 BatchOps 原有交付确认 |
| `awaiting_admin` | 检出疑点，或修复成片完成复查 | 展示当前视频、问题和文字建议；等待管理员决定 |
| `repairing` | 已记录管理员批准的修复命令，正在配音/成片/复查 | 展示处理中；进程中断或上次失败时用 `resume` 续跑同一决定 |
| `inspection_failed` | 检查证据未完成 | 展示失败状态，调用 `retry` 或交管理员处置；不可显示成“无问题” |

**首轮 `clean` 可以沿原有交付路径继续。修复后的每一轮，即便机器复查为 `clean`，也必须再次由管理员决定。** `release_ready` 是带文件身份的模块建议，真正的客户放行仍由 BatchOps 自己的权限与版本流程处理。

## 输入合同

`start` 读取 UTF-8 JSON；以下字段标识同一个最终 TTS revision：

```json
{
  "item_id": "batchops-item-123",
  "revision_id": "content-version-and-tts-attempt-id",
  "video_path": "/private/final.mp4",
  "video_sha256": "64位十六进制 SHA-256",
  "source_path": "/private/main.py",
  "source_sha256": "64位十六进制 SHA-256",
  "subtitle_path": "/private/final.srt",
  "subtitle_sha256": "64位十六进制 SHA-256",
  "tts_profile": {"provider": "qwen_audio", "model": "qwen-audio-3.0-tts-plus", "voice": "longanlufeng", "speech_rate": 0.9},
  "render_profile": {"aspect_ratio": "16:9", "quality": "m", "pixel_width": 1280, "pixel_height": 720, "frame_rate": 30},
  "question": {"question": "已知……，求……"}
}
```

`item_id`、`revision_id`、`video_path`、`source_path` 必填。建议提供视频、源码及字幕 SHA：模块重算并校验，防止把不同版本的产物混在一起。`subtitle_path` 与题目可选，但缺字幕会降低问题定位精度。路径必须是模块进程可读的受控本地文件；COS/TOS 下载、鉴权、同版本资源归属由 BatchOps 适配层处理，不把临时签名 URL 或密钥写入 JSON。

要让模块**自己执行修复**，`start` 还需 `--source-pack` 指向与 `source_path` 同版的完整源码包，并选一种执行方式：

- `--repair-mode local --unburned`：未烧字幕原片和唯一字幕时间窗可用时，局部重配音并合成完整 MP4。必须提供原片实际使用的 `tts_profile`；仅支持兼容的 Qwen Audio 参数，避免补音突然换音色。FFmpeg 必须带 libass `subtitles` 滤镜，`scripts/preflight.sh --local-repair` 可预检。语速变化过大等情形会返回错误，需选择完整渲染路线。
- `--repair-mode worker`：提交隔离 Render 子节点完整渲染，必须提供原 `tts_profile` 与 `render_profile`，防止竖屏、音色和帧率变化。需要 `.[batchops]` 与 `.env.example` 中列出的控制面、TOS 等环境变量。测试任务不会关联客户交付单。

## 输出合同

`dev-pb2-cycle start/status/decide/retry/resume` 在标准输出返回 JSON。稳定的上层字段是 `schema_version`、`item_id`、`phase`、`round`、`inspection_status`、`revision_id`、`video_path`、`video_sha256`、`issues`、`release`、`decision_count`；`repairing` 时另带当前决定与 `last_error`。完整审计在会话目录 `cycle.json`，不要把整个会话文件直接展示给前端。

每条 `issues` 含 `issue_id`、`kind/category/priority`、`time_seconds`、`source_line`、`original_text`、`observed_text`、`proposed_text`、`repair_mode` 和 `reason`。`observed_text` 是 ASR 听写，可能识别错误；对纯音频读错，建议文字可能和源码相同，`repair_mode=resynthesize_audio` 表示只需重新配音。播放器跳转到 `time_seconds`，并允许管理员修改 `proposed_text` 后提交。

## 管理员动作

```bash
dev-pb2-cycle start --request request.json --session /private/pb2/item-123 \
  --work-root /private/pb2/work --source-pack /private/source.tar \
  --unburned /private/unburned.mp4 --repair-mode local
dev-pb2-cycle status --session /private/pb2/item-123
dev-pb2-cycle decide --session /private/pb2/item-123 \
  --actor admin-42 --action approve_repair --edits edits.json
dev-pb2-cycle decide --session /private/pb2/item-123 \
  --actor admin-42 --action accept_as_is
dev-pb2-cycle retry --session /private/pb2/item-123
dev-pb2-cycle resume --session /private/pb2/item-123
```

确认 AI 建议或手工改文时，`edits.json` 例子为 `[{"issue_id":"问题 ID","new_text":"管理员确认的完整读法"}]`。若修复后的机器结果无候选、管理员却听出新问题，可用 `[{"source_line":123,"old_voiceover":"完整旧旁白","new_voiceover":"完整新旁白"}]` 指定当前源码中的口播。模块核对当前源码、旧文本、revision 和 SHA；无匹配或过期决定不执行修复。

`accept_as_is` 生成 `release_ready`，其中 `release` 绑定当前 revision、视频 SHA 和管理员决定 ID。`approve_repair` 先持久保存批准的决定并进入 `repairing`，再执行文字替换、配音、完整成片和重新筛查，完成后返回 `awaiting_admin`。进程中断或执行报错时，使用 `resume` 续跑**同一决定**，不能在此时提交另一套文字；`inspection_failed` 则用 `retry` 重新筛查。每轮修复保存旧版证据和新成片，不覆盖输入视频。

## 接入 BatchOps 时的责任

BatchOps 最终放行入口在 `apps/batchops/control/components/admin/production-stage-panel.tsx` 的“管理员通过并释放给客户”，后端为 `apps/batchops/intake_api/app/routes/delivery_review.py` 的 `tts-completion/accept`。现有 `tts-completion/rerender` **只接收 `reason`，复用已经锁定的源码归档**；它不能接收 `voiceover_overrides`，不能直接用于“确认改文”。接入方需创建新的权威内容 revision / 源码包，绑定批准文字与原 TTS 版本，走正式 TTS 和完整成片流程，再以新 SHA、新 revision 调用模块复查。完整接线顺序和文件位置见[教程](batchops-adapter-guide.md)。

模块的本地或隔离子节点修复可以作为独立使用的闭环；其成片进入正式 BatchOps 前，接入方仍需负责产物入库、版本关系、访问控制和交付审计。不要把模块的 `release_ready` 直接解释成已经完成客户发送。
