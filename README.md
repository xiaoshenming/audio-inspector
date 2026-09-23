# Audio Inspector

一个面向教学成片的、只采证不拦截的音频检测工具。输入最终视频和期望旁白，输出带时间点的 STT 差异、英文/字母风险、多音字声学候选，以及可播放的 HTML 人工复核报告。

## 当前定位

这是经过历史批量验证的工程化起点，不是生产质量闸门：

- `transcript` lane：`faster-whisper` 中文转写、期望旁白比对、英文/字母候选；
- `pronunciation` lane：可选的 G2PW/词典候选与带声调声学核验；
- 每条结果区分 `completed`、`failed_open`、候选和确认证据；
- 自动结果只能提示“值得核听”，不能替代人工判断TTS是否真的读错。

仓库不包含任何客户视频、字幕、源码、任务ID、服务器地址、数据库、模型权重或密钥。

## 五分钟跑通 transcript lane

要求：Linux、Python 3.11+、FFmpeg/ffprobe。首次运行会由 `faster-whisper` 下载所选模型；生产服务器建议预先下载并固定模型目录。

```bash
git clone https://github.com/xiaoshenming/audio-inspector.git
cd audio-inspector
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
audio-inspector --help
```

准备 `manifest.json`：

```json
{
  "items": [
    {
      "item_id": "sample-001",
      "video_path": "/srv/audio-inspector/input/sample-001.mp4",
      "expected_text": "我们先观察图形，再写出计算过程。"
    }
  ]
}
```

执行批量检测：

```bash
audio-inspector batch \
  --manifest manifest.json \
  --output output/run-001 \
  --model small \
  --device cpu \
  --compute-type int8 \
  --concurrency 1 \
  --model-workers 1
```

启动复核页面：

```bash
audio-inspector serve \
  --manifest manifest.json \
  --output output/run-001 \
  --host 127.0.0.1 \
  --port 8765
```

从工作电脑建立SSH隧道后访问 `http://127.0.0.1:8765/`：

```bash
ssh -L 8765:127.0.0.1:8765 your-server-alias
```

## 如何判断结果

- `clean`：检测lane完整运行且未发现候选，不代表人工100%确认正常；
- `low`：普通数学字母等记录，默认不作为问题；
- `medium/high`：应点击时间点人工核听；
- `failed_open`：检测没有完成，绝不能当作“音频通过”；
- `decision=confirmed`：只表示对应声学lane满足确认合同，最终交付仍建议人工抽检。

## 多音字声学lane

多音字检测需要额外模型，先阅读[多音字检测教程](docs/polyphone.md)。不要把普通 STT 文本当成带声调发音结论。

## 最终成片双视角初筛

需要同时检查“最终源码旁白是否缺内容”和“成片读法是否偏离旁白”时，参见[双视角初筛流程](docs/screening-workflow.md)。该流程可选用 Qwen Audio 3.1 ASR 与 DeepSeek，分别保存两类候选证据，并生成可跳转时间点的人工复核页。结果只用于人工核听，不改变视频交付状态。

需要让同事在线保存人工结论时，可使用[受管理员会话保护的复审服务](docs/human-review-server.md)。

## 服务器部署

部署、资源预检、持久批任务、报告访问和恢复方法见[服务器部署与验证](docs/server-deployment.md)。架构和接入生产批处理系统的边界见[架构说明](docs/architecture.md)。

## 开发验证

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check src tests
python -m compileall -q src tests
```

## 隐私与安全

- 不要提交真实视频、字幕、源码、manifest、输出报告、日志或 `.env`；
- 公共仓库只允许合成fixture；
- Review Server只映射manifest明确列出的文件，默认监听 `127.0.0.1`；
- 对外访问优先使用SSH隧道，不要直接开放端口；
- 生产接入必须校验视频SHA、期望文本SHA、模型SHA和检测器版本。
