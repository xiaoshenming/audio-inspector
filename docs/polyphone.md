# 多音字声学检测教程

## 为什么单独一条lane

普通STT适合发现内容差异和英文片段，但不能可靠判断汉字声调。多音字lane把“语境中应该读什么”和“音频实际读成什么”分开留证。

## 依赖

```bash
python -m pip install -e '.[pronunciation]'
```

还需要准备并固定：

- G2PW模型目录；
- G2PW tokenizer目录；
- Hugging Face phonetic CTC模型目录；
- 字幕VTT，或transcript lane输出的时间轴；
- 可选的风险短语词典。

模型权重不进入Git。部署时记录模型目录、版本、SHA和许可证。

## Manifest字段

每条至少包含：

```json
{
  "item_id": "sample-001",
  "template": "generic",
  "video_id": "sample-001",
  "video_path": "/srv/audio-inspector/input/sample-001.mp4",
  "source_path": "/srv/audio-inspector/input/sample-001.py",
  "subtitle_path": "/srv/audio-inspector/input/sample-001.vtt"
}
```

## 两阶段执行

第一阶段只准备语境候选，可单独检查切词和期望读音：

```bash
audio-inspector-polyphone-prepare \
  --manifest manifest.json \
  --output output/polyphone \
  --g2pw-model /srv/audio-inspector/models/g2pw \
  --g2pw-tokenizer /srv/audio-inspector/models/bert-base-chinese
```

第二阶段运行声学模型，并逐条写入可续跑结果：

```bash
audio-inspector-polyphone-run \
  --manifest manifest.json \
  --prepared output/polyphone/prepared.jsonl \
  --output output/polyphone \
  --phonetic-model /srv/audio-inspector/models/phonetic-ctc \
  --g2pw-model /srv/audio-inspector/models/g2pw \
  --g2pw-tokenizer /srv/audio-inspector/models/bert-base-chinese \
  --batch-size 2
```

生成报告：

```bash
audio-inspector-polyphone-report \
  --results output/polyphone/results.jsonl \
  --output output/polyphone/report.html
```

## 判定边界

- 首批先限制20条并核对内存、swap和速度；
- 多时间窗读出另一合法异读，只能进入高优先级人工复核；
- 轻声、连续变调、切词错误和声母漏识别是常见误报；
- 不得按具体客户任务ID写特判；
- 工具失败、缺时间轴、未发现问题必须是不同状态。
