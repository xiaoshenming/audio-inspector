# 600 条样本交接

Git 分支 `DEV-PB2` 保存全部此前提交历史、造样代码、两批 `oracle` 文本标签、首次冻结结果及诊断重算结果；见 `benchmarks/2026-09-23/`。因此只拿到 Git 仓库也能读懂本次调试和评测过程。

600 条 MP3、MP4、字幕、源码和各阶段逐条结果约 846 MB，位于本工作目录的 `input/synthetic-tts-20260923/` 与 `input/synthetic-tts-challenge-20260923/`，因体积及内部路径不提交 Git。随同交接的独立归档为 `DEV-PB2-samples-600.tar`（约 832 MiB）。归档不含密钥。SHA-256：`7ce0259b34fe8671d8e4d96969675a9999061823d4f4729b55dc049df68db30d`。

同事收到代码和归档后，在 DEV-PB2 仓库根目录执行：

```bash
mkdir -p input
tar -xf /path/to/DEV-PB2-samples-600.tar -C input
python tools/rebase_samples.py input/synthetic-tts-20260923 input/synthetic-tts-challenge-20260923
dev-pb2-synthetic-eval --root input/synthetic-tts-20260923
dev-pb2-synthetic-eval --root input/synthetic-tts-challenge-20260923
```

`rebase_samples.py` 会把归档中原机器的绝对路径改为解压位置，并检查 600 个视频与源码都存在。校准/挑战的**首次冻结结果**请看 Git 中的 `*-frozen-results.json`；重新执行评测得到的是修正规则后的诊断结果，不能冒充首次盲测。`natural_risk_unlabeled` 的 54 条函数记号样本没有预设真假，需人工核听。

打包前已逐条核对 600 个 MP3 与 600 个 MP4 的 SHA-256，均与原 TTS 结果记录相符。转交文件时可先用上面的归档 SHA-256 核对整个 tar。
