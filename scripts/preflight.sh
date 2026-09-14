#!/usr/bin/env bash
set -euo pipefail

command -v python3 >/dev/null
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
python3 -c 'import audio_inspector, faster_whisper, pypinyin, cn2an; print("python imports: ok")'
python3 -m audio_inspector.cli --help >/dev/null
printf '%s\n' 'audio-inspector preflight: ok'
