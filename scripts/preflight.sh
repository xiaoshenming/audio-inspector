#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--local-repair" ) ]]; then
  printf '%s\n' 'usage: preflight.sh [--local-repair]' >&2
  exit 2
fi

command -v python >/dev/null
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
python -c 'import dev_pb2, faster_whisper, pypinyin, cn2an; print("python imports: ok")'
dev-pb2 --help >/dev/null
dev-pb2-cycle --help >/dev/null
printf '%s\n' 'DEV-PB2 inspect: ok'
if [[ $# -eq 1 ]]; then
  if ! python -c 'from dev_pb2.repair_media import supports_burned_subtitles; raise SystemExit(0 if supports_burned_subtitles() else 1)'; then
    printf '%s\n' 'DEV-PB2 local repair: ffmpeg_subtitles_filter_required (install FFmpeg with libass)' >&2
    exit 2
  fi
  printf '%s\n' 'DEV-PB2 local repair: ok'
fi
