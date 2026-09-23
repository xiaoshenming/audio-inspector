# 同事接线教程：将 DEV-PB2 放在 BatchOps 最终交付前

目标：最终带配音视频完成后调用独立模块；初轮无疑点时走原有确认发送流程，有疑点时让管理员核听并决定放行或按可编辑建议重配音；新成片再交管理员确认，可重复。**本仓库没有修改 BatchOps。** 以下文件位置是接线参考，不表示这些按钮和接口已经集成。

## 1. 先确认现有接点

| 用途 | BatchOps 现有位置 | 接线要点 |
|---|---|---|
| 最终视频及“管理员通过并释放给客户” | `apps/batchops/control/components/admin/production-stage-panel.tsx` 的 `FinalReviewAction` | 在现有最终视频旁展示 DEV-PB2 状态、时间点、原文/听写/建议新文与可编辑输入框；放行仍调原来的动作 |
| 客户放行接口 | `apps/batchops/intake_api/app/routes/delivery_review.py` 的 `tts-completion/accept` | 已有管理员权限与 `Idempotency-Key`；只在模块返回绑定当前视频的 `release_ready` 后走原有流程 |
| 现有 TTS 重渲染接口 | 同文件的 `tts-completion/rerender`；请求模型在 `delivery_route_contracts.py` | 仅接受 `reason`，`delivery_retry.py` 复用锁定的 `GenerationJob` 源码。**它不会应用改文，不可直接接“确认修复”。** |
| TTS 完成列表 | `apps/batchops/intake_api/app/schemas/delivery.py` 的 `completion_view` | 只返回视频 URL、状态等摘要，没有最终源码、字幕或 SHA；需在服务端关联权威产物 |
| 前端调用 | `apps/batchops/control/lib/api/client.ts` 的 `acceptTtsCompletion` / `rerenderTtsCompletion` | 保留原交付调用；新增 DEV-PB2 会话读取与管理员提交适配器 |

## 2. 把同一版本的资源交给模块

适配器从 `TTSCompletionJob` 出发，关联 `source_generation_job_id`、`selected_content_version_id`、`render_job_id` 与对应产物记录，确认视频、实际配音源码、字幕、题目均来自**同一次最终配音版本**。不能只凭列表页的 `final_video_url` 推断资源归属。下载 COS/TOS 资源到私有工作目录，计算 MP4 与源码 SHA，再写 `request.json`。

| DEV-PB2 字段 | 推荐来源与核对方式 |
|---|---|
| `item_id` | BatchOps 的 `IntakeItem.id`，在模块会话与任务之间保持唯一映射 |
| `revision_id` | 内容版本 ID 与最终 TTS/render 尝试 ID 的组合；一旦成片或源码变化就换 ID |
| `video_path` / `video_sha256` | 最终配音 MP4 的受控本地副本及实算 SHA；不是静音预览 |
| `source_path` / `source_sha256` | 该 MP4 实际使用的 `main.py`，从已锁定源码归档提取并实算 SHA |
| `subtitle_path` | 同一 TTS 尝试的 SRT，若没有则留空，不借用旧版字幕 |
| `subtitle_sha256` | 有 SRT 时实算 SHA；模块将其纳入审查缓存及版本校验 |
| `tts_profile` | 原片实际使用的 provider、model、voice、speech_rate；修复时原样继承 |
| `render_profile` | 原片的画幅、分辨率、帧率和质量；完整重渲染时原样继承 |
| `question` | 该题目对应的已选内容版本中的题干和必要上下文 |
| `--source-pack` | 与 `main.py` 同版的完整源码包，供模块批准后修复 |
| `--unburned` | 同版未烧字幕原片；选择 `local` 修复时需要 |

`request.json` 形状见[对外协议](batchops-integration.md#输入合同)。模块只收路径，不负责 COS/TOS 鉴权与下载。调用方应设置私有目录权限及清理策略，密钥只放进环境变量。

若无法确定原配音模型或音色，不要猜一个默认值做局部补音；先从正式 TTS 任务的权威参数补齐 `tts_profile`。`worker` 模式还必须取得原渲染规格，避免重新出片时擅自改成横屏或改变帧率。

## 3. 启动独立会话

每个最终 TTS revision 使用独立、持久的 `--session` 目录。推荐用 CLI 作为进程边界；同样可以从 Python 调用 `dev_pb2.review_cycle.start/view/apply/retry_inspection/resume_repair`。

```bash
dev-pb2-cycle start --request /private/item-123/request.json \
  --session /private/pb2/sessions/item-123-rev-1 \
  --work-root /private/pb2/evidence \
  --source-pack /private/item-123/source.tar \
  --unburned /private/item-123/unburned.mp4 --repair-mode local
```

`--repair-mode worker` 适用于没有可用未烧字幕原片、需重画面或语速无法自然对齐的任务；它调用隔离 Render 子节点，需要 `.[batchops]` 和 `.env.example` 所列控制面/TOS 参数。先在独立模块验证，再由 BatchOps 适配器决定如何把批准的源码版本及成片纳入正式任务。不能把隔离测试 job 当成客户任务。

`local` 路线在烧录修正后的字幕时需要带 libass 的 FFmpeg `subtitles` 滤镜。预检：`ffmpeg -hide_banner -filters | rg ' subtitles '`；没有结果时，这台机器的本地路线无法完成成片，应使用具备该滤镜的 FFmpeg 构建，或选择 `worker` 路线。仅看到 `ffmpeg -version` 成功不足以证明可用。

将 `status` 输出中的 `phase` 存入 BatchOps 自己的业务状态或投影，保留 `session` 定位符。模块输出的 `video_path` 是服务端文件路径，前端需要由 BatchOps 自己生成受权限保护的可播放 URL；问题卡片的 `time_seconds` 用于播放器跳转。

## 4. 处理三个分支

1. `release_ready`：初轮 `clean` 可走原有“管理员通过并释放给客户”路径；或者候选被管理员选为“没问题，放行”。调用前再次核对当前 BatchOps 任务所指的 revision 与视频 SHA 等于 `release`。模块的 `release_ready` 不执行客户发送。
2. `awaiting_admin`：展示当前视频和全部 `issues`。管理员点“没问题，放行”时调用 `dev-pb2-cycle decide --action accept_as_is --actor <管理员 ID>`；点“确认修复”时提交 `issue_id + new_text` 的 `edits.json`，调用 `--action approve_repair --edits ...`。管理员可改建议文字，模块只执行最终提交的文字。
3. `inspection_failed`：显示未完成而非“没问题”，调用 `dev-pb2-cycle retry --session ...`；重试仍失败时保留原成片与错误证据，转管理员处理。不要把 `failed_open` 当作 clean。

管理员提交修复后，会话先进入 `repairing`。若配音、渲染或进程中断，适配器读取 `last_error`，用 `dev-pb2-cycle resume --session ...` 续跑已经保存的同一决定；这时不接收另一条“确认修复”请求。只有重配并复筛完成才回到 `awaiting_admin`。

`approve_repair` 完成后模块会产生新源码、字幕、完整 MP4 和再次筛查结果，**总是回到 `awaiting_admin`**。即使本轮机器检查为 `clean`，管理员仍需听新视频并决定放行或再改一轮。管理员听出机器未报的新问题，可用协议中的 `source_line + old_voiceover + new_voiceover` 直接指定新口播。

## 5. 正式修复需生成新权威版本

模块单独使用时，`local` 或 `worker` 执行器已经能闭环。接入真实 BatchOps 交付时，同事需要把管理员批准的 `voiceover_overrides` 及新源码包写成**新的权威内容 revision**，关联父 revision、管理员 ID、决定 ID、旧/新 SHA 与新 TTS 尝试；再走正式 TTS 与成片。现有 `rerender` 只复用旧源码，不能替代这一步。新成片要构造新 `request.json`，重新调用模块检查，不能复用旧的 `release_ready` 或候选结果。

请把“模块会话决定”和“BatchOps 正式版本/交付状态”在适配器内明确区分：模块负责筛查与独立修复，BatchOps 负责客户任务版本、权限、产物 URL 和发送。适配器只有在读取到当前 revision 的 `release_ready` 且文件 SHA 相符时，才让原放行接口处理它。

## 6. 最小接线验收

1. 一条首轮 `clean` 视频：拿到 `release_ready`，原有发送确认动作依然可用；未主动创建修复任务。
2. 一条 `candidate` 视频：卡片可跳到疑点位置；改写输入框文字后，确认操作生成**新**源码与完整视频。
3. 修复后 `clean`：页面仍显示待管理员确认，确认前不能把旧版或新版标为已发送；管理员可再次指定口播并重复修复。
4. 旧 revision、错误 SHA、无效 `issue_id`、重复提交、检查失败：不会把别的成片错误放行，也不会重复创建 TTS 任务。
5. 交付记录能追溯管理员、父/子 revision、批准文字、视频与源码 SHA；失败时旧版仍可播放，且保留错误原因。

独立模块验证结果见[真实样本闭环](real-152-closure.md)；它证明模块可操作，不代表 BatchOps 接线已经完成。
