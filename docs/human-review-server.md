# 在 B2B 服务器复审初筛候选

`audio_inspector.review_server` 是独立的人工复核页。它读取冻结的 `candidates.json` 与白名单 MP4，按问题时间点播放视频，把“正确 / 漏字 / 不正确 / 待定”保存到独立 SQLite，并逐次写入审计流水。评审同时支持整条视频和单个候选。不会修改 BatchOps 视频任务或质量状态。

## 数据目录

```text
review-152/
├── candidates.json
├── videos/<item_id>.mp4
└── reviews.sqlite       # 首次启动自动创建，必须持久化和备份
```

只复制本批需要复核的视频。`candidates.json` 来自 `audio-inspector-screening-report` 生成的 `screening-review/candidates.json`。视频按 `item_id` 白名单提供，支持 HTTP Range。不要把原始样本或 SQLite 提交到仓库。

## 鉴权与部署

服务通过 `AUDIO_REVIEW_AUTH_URL` 校验浏览器带来的 B2B 管理员 cookie。此 URL 应指向同机 Intake API 的 `/v1/auth/admin-session`。每个页面、接口、视频和导出请求都检查会话；未登录返回 401，鉴权服务不可用返回 503。浏览器先登录现有 8085 管理台，再访问同一主机的复审端口。登录 cookie 的 Path 必须覆盖复审站路径。

示例 systemd 单元见 `deploy/systemd/audio-inspector-review.service`。正式部署前检查端口、服务用户权限、数据目录剩余容量和公网访问控制。数据目录应仅允许服务用户读取，SQLite 写入目录需持久化。健康检查 `/healthz` 不暴露样本内容。评审者需在页面填写姓名；后端会留下每次修改的审计记录。

## 验收

1. 匿名 `/api/state`、`/media/<item_id>.mp4` 与 `POST /api/reviews` 均应返回 401。
2. 有效管理员会话能列出冻结候选；视频 Range 请求返回 206，能跳到问题时间点。
3. 分别对视频和单个问题保存结论，刷新后仍显示；SQLite `review_audit` 增加记录。
4. “导出全部评审记录”生成 CSV；人工填写的姓名、结论和备注可对应到目标 ID。
5. 服务重启后数据保留，原 B2B API、8085 和视频生产服务健康状态保持正常。
