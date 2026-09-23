# DEV-PB2 → BatchOps 接入合同

## 位置

当前 BatchOps 管理台在 `production-stage-panel.tsx` 的最终阶段展示带配音成片，并通过 `acceptTtsCompletion` 执行“管理员通过并释放给客户”。DEV-PB2 应在最终 MP4、最终源码和字幕都已固定后异步运行；管理台在该按钮旁展示筛查状态与问题卡片。独立模块不写 BatchOps 数据库、不发布客户视频、不在渲染链路安装质量阻断。

```text
正式 TTS 成片 + 最终源码/字幕 + revision/SHA
 → DEV-PB2 inspect
 → clean：标记筛查完成，原有交付路径照常进行
 → candidate：显示时间点、原文、听到的文字和建议新文
      ├─ 管理员“没问题，通过”：记录 accept_as_is，继续原有交付确认
      └─ 管理员改写或确认新文：记录 approve_repair
          → BatchOps 依据 voiceover_overrides 创建新 revision
          → 重新配音并合成完整 MP4
          → 新 SHA、新 revision 重新筛查；管理员再次确认
 → failed_open：显示未完成的阶段和原因，允许重试或人工处置；不称为“没问题”
```

## 输入和返回

调用方把 COS 地址下载或挂载为受控本地文件后，传给 `dev-pb2 inspect`。首版命令行请求至少有 `item_id`、`revision_id`、`video_path`、`source_path`；推荐加 `subtitle_path`、题目上下文、最终文件 SHA。不要把临时签名 URL 或密钥写入结果。BatchOps 适配器负责从其权威任务中确认“这些资源属于同一次最终 TTS revision”；DEV-PB2 负责重新算 SHA 并校验传入 SHA。物理文件与 revision 不一致时不运行。

`inspection.json` 的三个关键字段是 `status`、`can_continue`、`needs_admin_review`。每条 `issues` 含：

- `issue_id`：同一输入和同一问题的稳定标识；
- `kind/category/priority`：源码缺漏或成片疑似读错，以及细类；
- `time_seconds/source_line`：点击核听位置及源码位置；
- `original_text`：当前最终源码的连续原文；
- `observed_text`：ASR 听到的连续文字，可能有识别误差；
- `proposed_text`：简短建议，管理员可直接改；
- `repair_mode`：`replace_voiceover_text` 或 `resynthesize_audio`。

对纯音频疑点，源码可能本来正确，此时建议文字与源码相同，`repair_mode=resynthesize_audio` 表示重配音，不应伪造一个源码文字差异。对源码旁白缺漏，建议文字来自模型，**必须由管理员核对后确认**。

## 人工决定与重做

`dev-pb2 decide` 返回 `dev-pb2.decision.v1`，包含 `action`、`actor`、`revision_id`、视频/源码 SHA、`idempotency_key` 和 `voiceover_overrides`。`accept_as_is` 对应管理员“没问题”；`approve_repair` 对应确认或改写修复文字。管理员提交 `issue_id + new_text`，模块只针对唯一的 `voiceover(text=...)` 原文生成整句旧文/新文对照；原文不唯一、版本过期、问题不属于当前结果时拒绝生成重做命令。多处同一口播的修改会合并成一条覆盖命令。

BatchOps 消费 `rebuild_final_video` 时应按幂等键只创建一次**新**版本：先在权威源码中应用已确认的口播替换，随后用原有正式 TTS 与视频合成流程制作完整成片，并保存父 revision、旧/新文本、管理员和旧/新 SHA。新版本必须重新审查；不能把旧结果复用为新版本的“通过”。修复失败时保留旧的可播放视频和证据，由管理员决定下一步。

## 为什么重做使用确定性编排

管理员已经确定“改哪段、改成什么”后，后续步骤有固定顺序：版本校验 → 文本替换 → 正式 TTS → 完整成片 → SHA 核对 → 再审查。交给 Agent 自由选择修改点或生产动作，会增加不可预测性，也难以证明最终 MP4 与批准文本一致。AI 仍可用于发现问题和生成**待确认**建议；如需复杂源码修复，可另走现有人工/Agent 修复流程，但不能绕过新的 revision 和复审。

## 接线前验收

1. `clean` 不改变现有“管理员通过并释放给客户”的条件；`candidate` 在 UI 展示 A/B 全部候选，不能只显示 A。
2. 视频可跳转到 `time_seconds`；管理员可修改 `proposed_text`，页面同时显示 `original_text` 与 `observed_text`。
3. 同一决定重试不创建第二个 TTS 任务；旧 revision 或 SHA 无法套用修复命令。
4. 重做后只审核新成片；旧结果、人工决定和输入 SHA 保留供追溯。
5. `failed_open` 有明确状态和人工重试入口，不能被统计为 clean。

当前分支实现了独立筛查、结果合同和人工决定命令；BatchOps 的前端按钮、持久任务状态、COS 输入适配、正式重配音与视频合成**尚未接线**。接线时应在 BatchOps 自己的仓库测试与部署，不要把这个基线误当成已上线流程。
