# 服务器部署与验证

本文用于在一台Linux验证服务器上部署并运行Demo。示例不包含真实地址、账号和凭据。

## 1. 资源预检

```bash
uname -a
python3 --version
ffmpeg -version | head -n 1
ffprobe -version | head -n 1
df -h /srv
free -h
nproc
```

如果启用PyTorch声学模型，必须再检查：

```bash
python -c 'import torch; print(torch.__version__, torch.cuda.is_available())'
```

不能用 `nvidia-smi` 代替PyTorch CUDA检查，也不能静默从GPU退回CPU。

## 2. 安装

```bash
sudo mkdir -p /opt/audio-inspector /srv/audio-inspector/{input,output,models}
sudo chown -R "$USER":"$USER" /opt/audio-inspector /srv/audio-inspector
git clone https://github.com/xiaoshenming/audio-inspector.git /opt/audio-inspector/app
cd /opt/audio-inspector/app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
audio-inspector --help
```

生产验证建议使用固定本地模型目录，并记录目录SHA；不要在正式批次启动后才临时下载模型。

## 3. 先跑1条，再跑20条

把视频复制到 `/srv/audio-inspector/input/`，创建manifest。先验证一条：

```bash
source /opt/audio-inspector/app/.venv/bin/activate
audio-inspector batch \
  --manifest /srv/audio-inspector/manifest.json \
  --output /srv/audio-inspector/output/canary-1 \
  --limit 1 --concurrency 1 --model-workers 1
```

必须确认：`total=1`、`succeeded=1`、`failed_open=0`、`report.html`存在，并能点击时间点播放。随后再用新输出目录跑20条；不要覆盖首条证据。

## 4. 持久运行

超过5分钟的批次使用systemd transient unit，避免SSH断开终止：

```bash
sudo systemd-run \
  --unit=audio-inspector-canary20 \
  --collect \
  --working-directory=/opt/audio-inspector/app \
  /opt/audio-inspector/app/.venv/bin/audio-inspector batch \
  --manifest /srv/audio-inspector/manifest.json \
  --output /srv/audio-inspector/output/canary-20 \
  --limit 20 --concurrency 1 --model-workers 1
```

查看进度：

```bash
systemctl status audio-inspector-canary20 --no-pager
journalctl -u audio-inspector-canary20 -f
cat /srv/audio-inspector/output/canary-20/progress.json
```

相同输出目录会复用已经完成的逐条JSON；不要同时启动两个写同一输出目录的进程。

## 5. 查看报告

```bash
source /opt/audio-inspector/app/.venv/bin/activate
audio-inspector serve \
  --manifest /srv/audio-inspector/manifest.json \
  --output /srv/audio-inspector/output/canary-20 \
  --host 127.0.0.1 --port 8765
```

工作电脑使用SSH隧道访问。验收时至少检查页面200、一个视频Range 206、候选时间点跳转、低风险字母折叠口径和 `failed_open` 显示。

## 6. 容量验证

依次测试1、2、4并发，记录：

- CPU与峰值RSS；
- swap变化；
- 音频总时长和墙钟时间；
- real-time factor p50/p95；
- 成功、降级和候选视频数。

不要直接照搬历史高并发参数。模型、CPU、视频时长变化都会改变安全并发。

## 7. 停止与恢复

```bash
sudo systemctl stop audio-inspector-canary20
```

停止后保留 `output/items/`。确认没有同名进程后，使用同一manifest和输出目录重新启动即可续跑。清理时只能删除明确的输出批次或可再生模型缓存，不能删除输入视频或业务数据库。

## 8. 生产接入前门槛

Demo运行成功不等于生产接入完成。至少还要证明：

- 输入视频、期望文本、模型和结果均有SHA身份；
- 检测异步运行，服务停机不会延迟或阻断视频交付；
- 100条shadow事件覆盖率不低于95%；
- 300条全量shadow中交付额外失败数为0；
- 高风险候选经过人工标注并报告precision；
- 随机抽听无风险视频估计漏检率。
