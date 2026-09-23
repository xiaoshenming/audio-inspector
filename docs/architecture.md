# DEV-PB2 模块结构

对外入口是 `dev_pb2.review_cycle` / `dev-pb2-cycle`。会话持久保存当前视频版本、检查、管理员动作、修复回执及历史；初轮干净时返回放行建议，发现疑点时等待管理员，修复后无论复查结果如何都再等管理员确认。模块不操作 BatchOps 的客户任务或交付状态。

```text
同版 MP4 + main.py + 可选 SRT / 题目 / 源码包
  → review_cycle.start → pipeline.run
      → qwen_asr / semantic_review / literal_asr / literal_reading
      → screening_report → inspection.json
  → clean：release_ready；candidate：awaiting_admin
  → review_cycle.apply(admin 决定)
      ├─ accept_as_is → release_ready
      └─ approve_repair → decisions → source_revision
           → repair_media（局部重配音）或 worker_render（隔离完整渲染）
           → pipeline.run（新 MP4 + 新源码）→ awaiting_admin
```

`manifest.py` 校验清单，`pipeline.py` 组织五个筛查阶段并发布 `clean/candidate/failed_open`。`decisions.py` 将管理员批准转成带 revision、文件 SHA 和幂等键的确定性口播替换。`source_revision.py` 修改源码包；`repair_media.py` 负责时间窗明确时的局部重配音与完整视频合成；`worker_render.py` 是独立 Render 子节点适配器。`review_cycle.py` 统一这些步骤，保存每轮审计及对外状态。

`synthetic_*`、`batch_eval.py`、`worker_batch.py` 等是样本与实验工具。`review_server.py` 是此前离线核听页，不是正式交付入口。测试媒体、密钥和临时工作目录不在 Git 中；Git 保存代码、文档和可复现的冻结文本证据。

源码、视频及管理员决定由 revision 与 SHA 绑定。检查阶段证据不完整时返回 `failed_open`；会话表现为 `inspection_failed`，可以重试，不会伪装成干净。对外字段与接入方式见[协议](batchops-integration.md)和[接入教程](batchops-adapter-guide.md)。
