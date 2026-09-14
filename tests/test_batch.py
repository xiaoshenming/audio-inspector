import json
import sys
import types
from pathlib import Path

from audio_inspector import batch


class FakeSegment:
    start = 0.0
    end = 1.0
    text = "我们观察图形"


class FakeInfo:
    duration = 1.0


class FakeWhisperModel:
    def __init__(self, *_args, **_kwargs):
        pass

    def transcribe(self, *_args, **_kwargs):
        return iter([FakeSegment()]), FakeInfo()


def test_batch_writes_resumable_results_and_report(monkeypatch, tmp_path: Path):
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"synthetic-test-bytes")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": [{
        "item_id": "sample-001",
        "video_path": str(video),
        "expected_text": "我们观察图形",
    }]}, ensure_ascii=False), encoding="utf-8")

    first = batch.run_batch(manifest, tmp_path / "output")
    second = batch.run_batch(manifest, tmp_path / "output")

    assert first["succeeded"] == 1
    assert second["succeeded"] == 1
    assert len(list((tmp_path / "output/items").glob("*.json"))) == 1
    assert (tmp_path / "output/report.html").is_file()


def test_manifest_rejects_duplicate_ids(tmp_path: Path):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"test")
    manifest = tmp_path / "manifest.json"
    row = {"item_id": "same", "video_path": str(video)}
    manifest.write_text(json.dumps([row, row]), encoding="utf-8")

    try:
        batch.load_manifest(manifest)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate item_id should fail")
