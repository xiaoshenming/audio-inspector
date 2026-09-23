import csv
import json

from audio_inspector.screening_report import _reportable, _source_priority, compile_candidates


def test_self_negating_model_findings_are_not_sent_to_staff():
    assert not _reportable({"confidence": "medium", "category": "audio_wrong_number",
                            "why": "数学上等价，故不报告"}, "audio")
    assert not _reportable({"confidence": "high", "category": "source_wrong_expression",
                            "source_quote": "十一分之二", "suggested_reading": "十一分之二",
                            "why": "计算无误"}, "source")
    assert _reportable({"confidence": "high", "category": "source_missing_object",
                        "source_quote": "已知向量与 b", "why": "缺少 a"}, "source")


def test_single_clear_gap_is_prioritized_but_optional_visual_detail_is_not():
    assert _source_priority([{"confidence": "high", "category": "source_missing_object",
                              "source_quote": "已知向量与 b 不共线"}]) == "A"
    assert _source_priority([{"confidence": "high", "category": "source_missing_object",
                              "source_quote": "该线在平面外"}] * 3) == "B"


def test_literal_reading_adds_previously_clean_video_to_priority_a(tmp_path):
    item_id = "01234567-89ab-cdef-0123-456789abcdef"
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    with (metadata / "samples.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "item_id", "external_key", "batch_name", "tts_status",
            "duration_seconds", "subtitle_path",
        ])
        writer.writeheader()
        writer.writerow({"item_id": item_id, "external_key": "1", "batch_name": "sample",
                         "tts_status": "accepted", "duration_seconds": "30",
                         "subtitle_path": ""})
    directory = tmp_path / "literal-reading/items"
    directory.mkdir(parents=True)
    (directory / f"{item_id}.json").write_text(json.dumps({"item_id": item_id,
        "status": "completed", "issues": [{"kind": "audio",
        "category": "audio_literal_formula", "confidence": "high",
        "source_quote": "f(x)", "asr_quote": "f左括号x右括号",
        "start_ms": 0, "time_seconds": 0}]}))
    result = compile_candidates(tmp_path)
    assert len(result) == 1
    assert result[0]["priority"] == "A"
    assert result[0]["audio_issues"][0]["category"] == "audio_literal_formula"
