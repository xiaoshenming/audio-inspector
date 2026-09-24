# 最终成片的双视角初筛

这套流程为人工复核挑选候选，所有结论均为证据，不阻断已生成视频。

## 输入与身份

- 每条样本固定最终 MP4、最终源码和期望口播；推荐同时保存字幕、源码及视频 SHA-256。
- `manifest.json` 中用唯一 `item_id` 关联 `video_path` 与 `source_path`。源码应是实际配音使用的最终版本，不能混用初稿。
- 问题原文可选，供源码语义审查判断变量和对象。不要把客户数据、密钥或签名 URL 提交到仓库。

## 两条证据链

1. **原始旁白审查**：从最终 `main.py` 的 `voiceover(text=...)` 提取逐句文本和源码行号，DeepSeek 只寻找旁白本身的病句、缺失变量、运算对象和不可朗读的文本。屏幕显示但讲解无需逐字念出的内容不算问题。
2. **成片听读审查**：Qwen Audio 3.1 把实际音轨转成带时间点的文本，再由 DeepSeek 比较最终旁白与 ASR。只留可引用两侧原文的数学对象差异；数字书写、大小写、标点、同义表达和 ASR 公式排版不直接算读错。源码中已存在的缺漏归入第一条链，避免重复和反向归因。
3. **字面读法补查**：Qwen 3.1 可能把“f 左括号 x 右括号”润色成 `f(x)`，因此另用 faster-whisper small 只听最终旁白中出现原样函数记号的字幕时间窗。只有源码含 `f(x)`、`g(0)` 等记号、逐字听写出现“左括号…右括号”一类成对读法且时间窗对齐时，才生成独立的 `audio_literal_formula` 候选；点坐标的括号不混入函数记号类别。

Qwen 的 SSE 句子内容会逐次累积；适配器把相邻最终事件切成增量片段。超过模型单次时长的音频按 240 秒切片，并将时间点加上切片偏移。空转写、请求失败与“完成且未发现候选”保持不同状态。

## 运行

在受控环境中提供 `DASHSCOPE_API_KEY`、`DASHSCOPE_ASR_ENDPOINT` 和 `DEEPSEEK_API_KEY`。B2B 当前使用的 ASR endpoint 已列在仓库根目录的 `.env.example`；TTS endpoint 也在同一文件。不要把密钥放入日志、源码或报告。也可以通过 `--endpoint` 传入端点。

```bash
dev-pb2-qwen-asr --manifest /private/batch/manifest.json \
  --output /private/batch/asr-qwen --workers 2

dev-pb2-semantic-review source \
  --manifest /private/batch/manifest.json \
  --questions /private/batch/metadata/questions.json \
  --output /private/batch/semantic-source --workers 3

dev-pb2-semantic-review audio \
  --manifest /private/batch/manifest.json \
  --asr-dir /private/batch/asr-qwen \
  --source-review-dir /private/batch/semantic-source \
  --output /private/batch/semantic-audio --workers 3

dev-pb2-literal-asr --manifest /private/batch/manifest.json \
  --output /private/batch/literal-asr-targeted --targeted --max-clips 3
dev-pb2-literal-reading --manifest /private/batch/manifest.json \
  --asr-dir /private/batch/literal-asr-targeted \
  --output /private/batch/literal-reading

dev-pb2-screening-report --dataset /private/batch
```

`screening-review/shortlist.csv` 是高优先级核听表，`all_candidates.csv` 包含扩展候选。表中预留人工结论和备注列。网页只播放 manifest 白名单内的视频，并让复核人从证据时间点开始核听。每条模型结果先经过原文引句校验；无法核对的引句不进入复审清单。

## 边界与下一步

- Qwen Audio 3.1 可能润色、补全或重排数学公式。ASR 的差异不是实际发音错误的证明，尤其要人工核听符号、上下标、声调和字母。
- 定向逐字听写并不替代人工耳听；一次只抽取每视频至多 3 个函数记号时间窗，若要完整逐处采证，可提高 `--max-clips` 后重跑，并抽听未命中的函数记号样本评估漏检。
- DeepSeek 可帮助找旁白病句，但也可能把合理概括误认为缺字。优先让员工审 A 级，再抽检 B 级和机器未报问题的样本，统计准确率与漏检率。
- 接入 B2B 时建议在成片完成后异步创建观察任务，绑定最终视频、最终源码、字幕和模型版本的摘要；检测失败只记录 `failed_open`，不改变成片交付状态。
