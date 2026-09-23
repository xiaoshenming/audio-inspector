import hashlib
import io
import tarfile

import pytest

from dev_pb2.repair_media import _audio_filter, _changed_cues, rebuild
from dev_pb2.source_revision import revise_pack, revise_source


def test_approved_voiceover_changes_only_selected_literal(tmp_path):
    source = 'with self.voiceover(\n    text="已知向量与 b 不共线"\n):\n    pass\n'
    override = {"source_line": 1, "old_voiceover": "已知向量与 b 不共线",
                "new_voiceover": "已知向量 a 与 b 不共线"}
    changed = revise_source(source, [override])
    assert "已知向量 a 与 b 不共线" in changed
    assert "with self.voiceover(" in changed
    with pytest.raises(ValueError, match="approved_voiceover_not_unique"):
        revise_source(source, [{**override, "source_line": 2}])

    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as tar:
        data = source.encode()
        info = tarfile.TarInfo("main.py")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    main = revise_pack(archive, [override], tmp_path / "patched")
    assert main.read_text() == changed
    with tarfile.open(tmp_path / "patched/source.tar") as tar:
        assert tar.extractfile("main.py").read().decode() == changed


def test_revoice_uses_exact_subtitle_cue_and_preserves_timeline(tmp_path):
    subtitle = tmp_path / "original.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\n已知向量与 b 不共线\n\n"
                        "2\n00:00:02,100 --> 00:00:04,000\n继续计算\n")
    cues, changes = _changed_cues(subtitle, [{
        "old_voiceover": "已知向量与 b 不共线",
        "new_voiceover": "已知向量 a 与 b 不共线"}])
    assert cues[0]["text"] == "已知向量 a 与 b 不共线"
    assert cues[1]["text"] == "继续计算"
    changes[0]["tempo"] = 1.05
    graph, output = _audio_filter(changes, 4.0)
    assert "atrim=duration=2.000" in graph
    assert "atrim=start=2.000:end=4.000" in graph
    assert "atrim=start=2.000:end=4.000,asetpts=PTS-STARTPTS,apad" in graph
    assert output == "[aout]"


def test_direct_rebuild_rejects_source_pack_from_another_revision(tmp_path):
    source = b'self.voiceover(text="other")\n'
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as tar:
        info = tarfile.TarInfo("main.py")
        info.size = len(source)
        tar.addfile(info, io.BytesIO(source))
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    video_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    inspection = {"item_id": "one", "revision_id": "r1",
                  "video_sha256": video_sha, "source_sha256": "a" * 64}
    decision = {**inspection, "action": "approve_repair",
                "voiceover_overrides": [{"old_voiceover": "other",
                                         "new_voiceover": "new"}]}
    with pytest.raises(ValueError, match="source_pack_main_mismatch"):
        rebuild(inspection, decision, video=video, unburned=video,
                subtitle=tmp_path / "none.srt", source_pack=archive,
                output=tmp_path / "out", api_key="test", tts_endpoint="test")


def test_direct_rebuild_rejects_changed_subtitle(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    subtitle = tmp_path / "subtitle.srt"
    subtitle.write_text("original", encoding="utf-8")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    inspection = {"item_id": "item", "revision_id": "r1",
                  "video_sha256": digest(video), "source_sha256": "a" * 64,
                  "subtitle_sha256": digest(subtitle)}
    decision = {**inspection, "action": "approve_repair",
                "voiceover_overrides": [{"source_line": 1}]}
    subtitle.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="stale_subtitle_revision"):
        rebuild(inspection, decision, video=video, unburned=video,
                subtitle=subtitle, source_pack=tmp_path / "source.tar",
                output=tmp_path / "output", api_key="test", tts_endpoint="test")
