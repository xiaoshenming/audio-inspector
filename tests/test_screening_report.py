import csv
import json

from dev_pb2.screening_report import _reportable, _source_priority, compile_candidates


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
    assert _source_priority([{"confidence": "high", "category": "source_missing_object",
                              "source_quote": "已知集合和集合 B"}]) == "A"


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


def test_unscored_exact_math_differences_remain_reviewable():
    cases = [
        ("audio_wrong_operator", "用 48 减 5 得到 43", "用48+5得到43"),
        ("audio_wrong_number", "解得 x 等于 25", "解得x=26"),
        ("audio_wrong_letter", "连接线段 XY", "连接线段XZ"),
        ("audio_missing_object", "面积为35平方米", "面积为35米"),
        ("audio_wrong_unit", "体积为75立方厘米", "体积为75平方厘米"),
    ]
    for category, source, actual in cases:
        assert _reportable({"category": category, "source_quote": source,
                            "asr_quote": actual, "why": "值得核听"}, "audio")


def test_equivalent_asr_notation_and_homophones_are_filtered():
    assert not _reportable({"category": "audio_wrong_operator", "confidence": "medium",
                            "source_quote": "已知 46 减 8 等于 38",
                            "asr_quote": "已知46-8=38", "why": "疑似运算符差异"}, "audio")
    assert not _reportable({"category": "audio_wrong_letter", "confidence": "medium",
                            "source_quote": "代回原条件", "asr_quote": "带回原条件",
                            "why": "两个词同音近音"}, "audio")
