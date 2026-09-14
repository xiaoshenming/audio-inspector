# 架构说明

## 处理链路

```text
最终视频 + 冻结期望旁白
  ├─ transcript lane
  │    ├─ faster-whisper分段转写
  │    ├─ 同音归一化后的全文相似度
  │    └─ 英文、字母和高风险片段候选
  └─ pronunciation lane（可选）
       ├─ G2PW/短语词典确定语境期望读音
       ├─ phonetic模型分析实际声学证据
       └─ 多时间窗多数投票
  → JSON逐条结果
  → summary + HTML人工复核
```

## 事实边界

三个事实不能混为一谈：

1. `transcript` 说明ASR听到了什么，不能单独证明某个汉字声调错误；
2. `pronunciation` 比较期望读音与声学证据，仍可能受切词、轻声和变调影响；
3. 人工结论才是业务复核结果，不能反向覆盖原始机器证据。

## 结果合同

每次检测保存：

- detector版本、模型名、音频时长、推理耗时和实时系数；
- finding ID、类型、严重度、开始/结束毫秒、转写片段和原因；
- required lanes、completed lanes和missing lanes；
- `failed_open`与“完成且无候选”必须分开。

单条finding和单任务finding数量有上限，避免报告或数据库无限膨胀。

## 接入生产批处理系统

推荐在成片上传并取得SHA后异步投递，主渲染流程不等待检测：

```text
Render上传成片
→ Transactional Outbox
→ Audio Inspection Worker claim/lease
→ 校验输入SHA并检测
→ 上传不可变结果bundle
→ 控制面保存摘要和artifact引用
→ 人工复核页面
```

生产请求至少携带tenant、generation、job、attempt、视频URI/SHA、期望文本URI/SHA、lane、检测器版本和幂等键。完整转写放对象存储，业务数据库只保存有界摘要和artifact引用。

## 禁止事项

- 不因口音、多音字或英文候选阻断已有可播放成片；
- 不在每个渲染容器重复加载STT模型；
- 不从不受信任的任意路径读取文件；
- 不把服务不可用或空结果写成检测通过；
- 不把历史样本精度直接外推到新的TTS供应商、音色和年级。
