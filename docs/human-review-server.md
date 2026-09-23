# 可选的人工核听页

`dev_pb2.review_server` 保留先前 152 条终审样本的独立核听能力：按候选时间点播放白名单 MP4，保存“正确 / 漏字 / 不正确 / 待定”的 SQLite 审计记录。它适合离线验样，**不执行** BatchOps 的“通过并释放给客户”或“确认修复”动作。正式集成要使用 [DEV-PB2 决定合同](batchops-integration.md) 接入管理台。

核听页读取冻结的 `candidates.json` 和 `videos/<item_id>.mp4`，以管理员会话 URL 校验每次页面、接口和媒体访问。视频按 manifest 白名单提供并支持 Range 跳转。旧 server9 的 systemd 单元不复制到本分支，以免新基线意外覆盖现有复审站。

本地验证可运行 `python -m dev_pb2.review_server --help`。样本、SQLite、密钥和会话 URL 均不提交 Git。
