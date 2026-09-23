import pytest

from dev_pb2.batch_eval import _edits, _literal_rewrite
from dev_pb2.decisions import decide


def test_literal_rewrite_proposes_natural_speech_and_keeps_math_object():
    assert _literal_rewrite("已知函数 f(x) 与 g(0) 的值") == \
        "已知函数 f 在 x 处的值 与 g 在 0 处的值"
    issues = [{"issue_id": "literal", "category": "audio_literal_formula",
               "original_text": "因此 f(x) 小于一", "proposed_text": ""},
              {"issue_id": "source", "category": "source_missing_object",
               "original_text": "求的值", "proposed_text": "求 a 的值"}]
    edits = _edits(issues)
    assert edits[0]["new_text"] == "求 a 的值"
    assert edits[1]["new_text"] == "因此 f 在 x 处的值 小于一"
    assert _literal_rewrite("f(x+3) 等于负 f(x)") == \
        "f 在 x 加 3 处的值 等于负 f 在 x 处的值"
    assert _literal_rewrite("已知函数 f(x) 为奇函数") == "已知函数 f 为奇函数"
    assert _literal_rewrite("因为 f(x) 是奇函数") == "因为 函数 f 是奇函数"
    assert _literal_rewrite("将 f(x) 化为二倍正弦") == "将函数 f 的表达式化为二倍正弦"
    assert _literal_rewrite("g(x_1) 等于 f(2x_1)") == \
        "g 在 x 下标 1 处的值 等于 f 在 2x 下标 1 处的值"


def test_missing_proposal_stays_visible_as_unrepairable():
    with pytest.raises(ValueError, match="issue_has_no_text_proposal"):
        _edits([{"issue_id": "x", "category": "source_missing_object",
                 "original_text": "求的值", "proposed_text": ""}])


def test_source_and_literal_edits_on_one_voiceover_are_combined(tmp_path):
    import hashlib

    source = tmp_path / "main.py"
    source.write_text('with self.voiceover(text="已知 f(x) 等于加一"):\n    pass\n')
    issues = [{"issue_id": "source", "kind": "source",
               "category": "source_missing_object", "source_line": 1,
               "original_text": "等于加一", "proposed_text": "等于 a 加一",
               "repair_mode": "replace_voiceover_text"},
              {"issue_id": "literal", "kind": "audio",
               "category": "audio_literal_formula", "source_line": None,
               "original_text": "已知 f(x) 等于加一", "proposed_text": "",
               "repair_mode": "resynthesize_audio"}]
    inspection = {"schema_version": "dev-pb2.inspection.v1", "status": "candidate",
                  "item_id": "one", "revision_id": "R1", "video_sha256": "v",
                  "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "issues": issues}
    command = decide(inspection, source, "simulation", "approve_repair", _edits(issues))
    assert command["voiceover_overrides"][0]["new_voiceover"] == \
        "已知 f 在 x 处的值 等于 a 加一"
    assert set(command["voiceover_overrides"][0]["issue_ids"]) == {"source", "literal"}
