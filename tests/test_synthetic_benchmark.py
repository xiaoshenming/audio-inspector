import json

from audio_inspector.semantic_review import voiceovers
from audio_inspector.synthetic_corpus import GROUPS, build_cases, write_corpus
from audio_inspector.synthetic_eval import _metrics
from audio_inspector.synthetic_tts import _subtitles


def test_corpus_has_balanced_seeded_truth_and_frozen_sources(tmp_path):
    cases = build_cases(3)
    assert len(cases) == len(GROUPS) * 3
    assert len({row["item_id"] for row in cases}) == len(cases)
    assert {row["length_tier"] for row in cases} == {"short", "medium", "long"}
    assert all(row["source_text"] != row["tts_text"]
               for row in cases if row["truth"] == "seeded_audio_mismatch")
    write_corpus(tmp_path, cases)
    row = next(x for x in cases if x["group"] == "source_missing_variable")
    source = (tmp_path / "sources" / f"{row['item_id']}.py").read_text()
    assert "".join(x["text"] for x in voiceovers(source)) == row["source_text"]
    questions = json.loads((tmp_path / "metadata/questions.json").read_text())
    assert questions[row["item_id"]]["question"] in row["expected_text"]


def test_subtitle_timeline_covers_complete_audio_duration():
    content = _subtitles("先看条件。再算结果。", 10)
    assert "00:00:00,000 -->" in content
    assert "00:00:10,000" in content
    assert content.count("-->") == 2


def test_seeded_metrics_keep_natural_risks_out_of_precision():
    cases = [
        {"group": "source_missing_variable", "truth": "seeded_source_defect",
         "candidate": True, "priority_a": True, "source_candidate": True,
         "audio_candidate": False},
        {"group": "audio_wrong_operator", "truth": "seeded_audio_mismatch",
         "candidate": False, "priority_a": False, "source_candidate": False,
         "audio_candidate": False},
        {"group": "clean_arithmetic", "truth": "intended_clean",
         "candidate": False, "priority_a": False, "source_candidate": False,
         "audio_candidate": False},
        {"group": "raw_function_notation", "truth": "natural_risk_unlabeled",
         "candidate": True, "priority_a": True, "source_candidate": False,
         "audio_candidate": True},
    ]
    result = _metrics(cases)
    assert result["source_lane_recall"] == 1
    assert result["audio_lane_recall"] == 0
    assert result["seeded_any_recall"] == 0.5
    assert result["seeded_precision_proxy"] == 1
    assert result["natural_candidate_rate"] == 1
