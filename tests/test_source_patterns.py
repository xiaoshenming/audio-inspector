from dev_pb2.source_patterns import (
    function_value_misphrasing,
    missing_perpendicular_object,
    missing_set_label,
)


def test_missing_first_set_label_uses_explicit_question_identity():
    rows = [{"line": 45, "text": "第3题，已知集合和集合 B，求交集。"}]
    issues = missing_set_label(rows, {"question": r"已知集合 $A=\{1\}$，$B=\{2\}$"})
    assert len(issues) == 1
    assert issues[0]["source_quote"] == "已知集合和集合 B"
    assert issues[0]["suggested_reading"] == "已知集合 A 和集合 B"
    assert missing_set_label(rows, {"question": "已知某个集合"}) == []
    assert missing_set_label([{"line": 45, "text": "已知集合 A 和集合 B"}],
                             {"question": "已知集合 $A$ 与 $B$"}) == []


def test_source_review_retains_pattern_when_model_returns_no_issues(tmp_path, monkeypatch):
    from dev_pb2 import semantic_review

    source = tmp_path / "main.py"
    source.write_text('self.voiceover(text="已知集合和集合 B")\n')
    monkeypatch.setattr(semantic_review, "_request",
                        lambda system, data, key: ({"issues": []}, {}))
    result = semantic_review.review_one(
        {"item_id": "one", "source_path": str(source)},
        {"one": {"question": "已知集合 $A$ 与 $B$"}}, {}, {}, "source", "fake")
    assert result["status"] == "completed"
    assert len(result["issues"]) == 1
    assert result["issues"][0]["detector"] == "set_label_pattern_v1"


def test_function_value_is_not_a_odd_function():
    rows = [{"line": 8, "text": "因为 f 在 x 处的值 是奇函数，所以继续。"},
            {"line": 9, "text": "将 f 在 x 处的值 化为二倍正弦。"}]
    issues = function_value_misphrasing(rows)
    assert len(issues) == 2
    assert issues[0]["suggested_reading"] == "函数 f 是奇函数"
    assert issues[1]["suggested_reading"] == "将函数 f 的表达式化为"


def test_perpendicular_condition_keeps_its_required_object():
    rows = [{"line": 11, "text": "已知 PA 垂直且等于 PD，继续证明。"}]
    issues = missing_perpendicular_object(rows)
    assert len(issues) == 1
    assert issues[0]["suggested_reading"] == "PA 垂直于 PD，且 PA 等于 PD"
    assert missing_perpendicular_object([{"line": 11,
        "text": "PA 垂直于 PD，且 PA 等于 PD"}]) == []
