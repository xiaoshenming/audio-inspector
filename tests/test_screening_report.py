from audio_inspector.screening_report import _reportable, _source_priority


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
