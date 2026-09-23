import io
import tarfile

import pytest

from dev_pb2.repair_media import _audio_filter, _changed_cues
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
