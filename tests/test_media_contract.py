"""Exercise the actual FFmpeg mux and subtitle burn without contacting a TTS API."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile

import pytest

from dev_pb2 import repair_media


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="FFmpeg and ffprobe are required")
def test_approved_voiceover_produces_playable_full_video(tmp_path, monkeypatch):
    original = tmp_path / "original.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(original),
    ], check=True)
    replacement_audio = tmp_path / "replacement.mp3"
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=2",
        "-c:a", "libmp3lame", str(replacement_audio),
    ], check=True)
    source = 'self.voiceover(text="旧旁白")\n'
    source_pack = tmp_path / "source.tar"
    with tarfile.open(source_pack, "w") as tar:
        data = source.encode()
        entry = tarfile.TarInfo("main.py")
        entry.size = len(data)
        tar.addfile(entry, io.BytesIO(data))
    subtitle = tmp_path / "original.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\n旧旁白\n", encoding="utf-8")
    monkeypatch.setattr(repair_media, "_post_tts", lambda *_: {
        "request_id": "fixture", "characters_billed": 3, "audio_url": "fixture://audio"})
    monkeypatch.setattr(repair_media, "_download_audio",
                        lambda _url, target: shutil.copyfile(replacement_audio, target))
    override = {"source_line": 1, "old_voiceover": "旧旁白", "new_voiceover": "新旁白"}
    sha = lambda content: hashlib.sha256(content).hexdigest()
    inspection = {"item_id": "item", "revision_id": "r1",
                  "video_sha256": sha(original.read_bytes()),
                  "source_sha256": sha(source.encode())}
    decision = {**inspection, "action": "approve_repair", "idempotency_key": "fixture-key",
                "voiceover_overrides": [override]}
    arguments = {"video": original, "unburned": original, "subtitle": subtitle,
                 "source_pack": source_pack, "output": tmp_path / "repaired",
                 "api_key": "fixture", "tts_endpoint": "fixture",
                 "tts_profile": {"provider": "qwen_audio", "model": "qwen-audio-3.0-tts-plus",
                                 "voice": "fixture-voice", "speech_rate": 1.0}}
    if not repair_media.supports_burned_subtitles():
        with pytest.raises(RuntimeError, match="ffmpeg_subtitles_filter_required"):
            repair_media.rebuild(inspection, decision, **arguments)
        return
    receipt = repair_media.rebuild(inspection, decision, **arguments)
    final = tmp_path / "repaired/final.mp4"
    assert final.is_file() and final.stat().st_size > 1000
    assert receipt["video_sha256"] == sha(final.read_bytes())
    assert "新旁白" in (tmp_path / "repaired/main.py").read_text()
    assert "新旁白" in (tmp_path / "repaired/corrected.srt").read_text()
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
        "-show_entries", "format=duration", "-of", "json", str(final),
    ], capture_output=True, text=True, check=True)
    media = json.loads(probe.stdout)
    assert {stream["codec_type"] for stream in media["streams"]} == {"video", "audio"}
    assert abs(float(media["format"]["duration"]) - 2.0) < 0.2
