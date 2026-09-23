# 合成 TTS 样本筛查量化

本实验只验证 Audio Inspector 的**筛查能力和运行完成率**，不是自动修复实验，也不能从人为注入样本直接推断真实客户视频的错误率。

## 冻结设计

- 默认随机种子 `20260923`，10 组各 54 条，共 540 条；每组 9 条校准、45 条留出，合计 90 / 450 条。短、中、长样本各 180 条。
- 与 B2B 当前正式配置对齐：`qwen-audio-3.0-tts-plus`、`longanlufeng`、语速 0.9。阿里云官方模型列表中有 3.1 Flash，但没有 3.1 TTS Plus；Qwen-Audio-TTS 的 HTTP 入口是工作空间域名下的 `/api/v1/services/audio/tts/SpeechSynthesizer`。
- 每条包含 `expected_text`（正确意图）、`source_text`（模拟最终源码旁白）、`tts_text`（送入 TTS 的文本）和不可变的 `truth` 标签。合成音频立即下载，封装为静态 MP4；字幕时间按源文句长近似分配，用于跳点核听。

| 类别 | 每组数量 | 预设标签 | 目的 |
|---|---:|---|---|
| 正确计算、正确解释 | 各 54 | `intended_clean` | 测无问题样本误报 |
| 源码缺变量、源码缺运算对象 | 各 54 | `seeded_source_defect` | 测原始旁白缺漏召回 |
| 送入 TTS 的加减、数字、字母、单位与源码不同 | 各 54 | `seeded_audio_mismatch` | 测听读差异召回 |
| 原样函数记号 `f(x)` | 54 | `natural_risk_unlabeled` | 观察 TTS 是否自然念出括号，不能预先指定真假 |
| 等价的概率说法换序 | 54 | `intended_clean` | 测 ASR/语义比较误报 |

**关键边界**：注入“音频差异”时，是故意把错误文本送给 TTS，模拟成片偏离最终源码；并不代表模型自己把正确输入念错。`natural_risk_unlabeled` 只能形成核听候选，需听原音才可定性。

## 运行顺序

在环境变量中提供 `DASHSCOPE_API_KEY`、`DASHSCOPE_TTS_ENDPOINT`、`DASHSCOPE_ASR_ENDPOINT`、`DEEPSEEK_API_KEY`。不要在命令、日志、代码或报告中写明文密钥。TTS 按字符计费；先运行 3 条、再运行校准 90 条，核实完成率和媒体格式后再运行留出 450 条。每阶段逐条保存，可同目录续跑。

```bash
audio-inspector-synthetic-corpus --output /private/synthetic-tts
audio-inspector-synthetic-tts --root /private/synthetic-tts --limit 3 --workers 1
audio-inspector-synthetic-tts --root /private/synthetic-tts --split calibration
# 校准清单固定后，执行 Qwen ASR、DeepSeek 源码/音频审查、定向逐字 ASR、字面读法检查。
audio-inspector-synthetic-tts --root /private/synthetic-tts --split holdout
# 全部媒体生成后，按 docs/screening-workflow.md 的命令对完整 manifest 续跑。
audio-inspector-screening-report --dataset /private/synthetic-tts
audio-inspector-synthetic-eval --root /private/synthetic-tts
```

## 报告口径

`screening-review/benchmark-results.json` 是机器可读结果；`benchmark-report.md` 是汇总表；`benchmark-cases.csv` 逐条列出种子标签、候选类型与 A/B 级。校准与留出分别统计：

- TTS、ASR、DeepSeek 和定向听写的完成、失败、缺失数；任何失败都不记成“无问题”。
- **注入缺陷检出率**：有候选的注入正例 / 可评估注入正例；同时分别计算源码链和音频链的归因召回。
- **正确控制样本误报率**：被标成候选的意图正确样本 / 可评估的正确控制样本。
- **查准代理**：被检出的注入正例 /（被检出的注入正例 + 被标出的正确控制样本）；排除未标注自然风险。它不是人工确认的生产查准率。
- A 级检出率、短中长分层、各类别候选比例、自然函数记号候选比例。

## 本轮 600 条实测

- 先冻结 540 条基线（90 校准、450 留出）：324 条注入缺陷检出 315 条（97.2%），162 条正确控制有 7 条进入候选（4.3%）；54 条无预置真假的 `f(x)` 风险中 49 条进入候选。留出与校准共用有限模板。
- 基线后发现 DeepSeek 部分明确音频问题未给 `confidence`，原筛选误丢证据；同时过滤 `减` 与 `-` 的等价记法及可解释的同音转写。对原 540 条重新计分，检出 324/324、正确控制候选 4/162。**原留出集已参与格式问题定位，这次重算不算盲测。** 原始基线副本保存在 `metadata/baseline-540-*`。
- 另造 60 条不同措辞挑战样本，不参与前述规则修正。首次冻结结果：50 条注入缺陷检出 49 条，10 条正确控制零候选；唯一漏检是“立方厘米”被读成“平方厘米”，原始 ASR 与 DeepSeek 已明确指出，但缺 `confidence` 时的确定性单位回退规则覆盖不全。首次结果保存在挑战目录 `metadata/frozen-challenge-*`。
- 补齐平方/立方厘米、平方米/立方米的单位差异回退规则后，同一挑战集重算为 50/50、0/10。**这是看过挑战结果后的诊断重算，不算新的独立验证。**
- 600 条全部 TTS、Qwen ASR、DeepSeek 源码与音频审查完成，无请求失败；共生成约 5.28 小时音频。筛选结果主要给人工复核，不能据此声称真实生产视频的查准率或漏检率。

若要检验真实课堂视频的漏检率，必须由同事在最终视频和机器未报问题的视频中人工抽听；本实验不能代替这一步。特别是注入音频差异用的是人为改写后的 TTS 输入，不代表 TTS 自发念错。
