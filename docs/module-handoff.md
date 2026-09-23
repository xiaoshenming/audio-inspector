# DEV-PB2 独立模块交接清单

此仓库的 `DEV-PB2` 分支保存完整 Git 历史。核心包为 `src/dev_pb2/`；它只读最终成片输入，所有新源码和新视频写入独立工作目录，不修改原任务。

## 给 BatchOps 的最小接口

1. **输入**：同一最终 revision 的 MP4、`main.py`、可选 SRT、题目上下文和文件 SHA。推荐同时给原始未烧字幕 MP4 与完整源码包，便于局部修复。
2. **筛查**：调用 `dev_pb2.pipeline.run(request, work_root)` 或 `dev-pb2 inspect`，得到 `inspection.json`：`clean / candidate / failed_open`、逐条证据、时间点、原文、ASR 听到的文字及建议新文。`clean` 才给出 `can_continue=true`；失败不伪装为 clean。
3. **人工决定**：候选问题由管理员核听，可以 `accept_as_is`，或逐条改写建议文字并调用 `dev_pb2.decisions.decide(...)` 得到带 revision、SHA 和幂等键的修复命令。批量评测中的 `simulated_model_proposal` 仅用于实验，不能映射为正式管理员批准。
4. **执行修复**：有未烧字幕原片且时间窗唯一、TTS 新旧时长接近时，调用 `dev_pb2.repair_media.rebuild(...)`。源码、SRT、完整 MP4 和 TTS 回执一并产出。其他情形用可选的 `dev_pb2.worker_render.render_and_inspect(...)`，把已批准的源码包送到 BatchOps 子节点完整重渲染，再取回 MP4 和字幕复筛。
5. **回传**：只回传新 revision 的结果和文件引用。仍是 `candidate`、`failed_open` 或渲染失败时，返回具体原因给管理员继续核听或指定新文字；不要把机器复筛当作客户交付批准。

## 可运行命令

```bash
python -m pip install -e '.[dev]'
dev-pb2 inspect --request request.json --work-root /private/pb2-runs
dev-pb2 decide --inspection /private/run/inspection.json --source /private/main.py \
  --actor reviewer-42 --action approve_repair --edits edits.json \
  --output /private/decision.json
dev-pb2-close-loop --request request.json --work-root /private/pb2-runs \
  --unburned /private/unburned.mp4 --source-pack /private/source.tar \
  --actor reviewer-42 --edits edits.json --output /private/closure
```

完整场景重渲染的适配器额外安装 `.[batchops]`，按仓库根目录 `.env.example` 提供控制面、Intake 签名入口、TOS 和测试租户凭据。`dev-pb2-worker-render` 使用已批准源码包调用现有 Render 控制面，不自行实现第二套 Manim 队列。B2B 隔离测试已验证最新启动模板的子节点能完成正式 TTS、720P 视频、字幕烧录、签名存储及模块复筛。

## 测试与边界

- 600 条合成样本的文本标签、冻结结果和诊断重算位于 `benchmarks/2026-09-23/`；媒体另见 [样本交接](sample-handoff.md)。
- 152 条真实终审视频的 65 条候选被用作隔离批测；同事复审站数据库在本轮读取时无已保存标签，所以报告只统计**新成片复筛无候选率**，不声称人工查准率。批测模块为 `shortlist.py`、`batch_eval.py`、`iterate.py`、`worker_batch.py` 和 `summary.py`，每条结果独立存档，可续跑。
- 局部重配音不修改动画时间轴；若文字长度变化使语速明显失真，模块返回完整场景重渲染需求。函数记号、ASR 误转写和模型新发现的候选仍可能需要下一轮人工判断。
- BatchOps 网页按钮、正式任务版本与客户释放动作均由同事接入。本仓库的子节点测试任务不属于客户完成单，也不会自动发布给客户。
