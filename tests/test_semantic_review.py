from audio_inspector.semantic_review import (
    _asr_adds_only,
    _spoken_canonical,
    _validate_audio,
    _validate_source,
    actionable_source_issue,
    voiceovers,
)


def test_voiceover_literals_keep_source_line_numbers():
    source = 'class Scene:\n    def construct(self):\n        with self.voiceover(text="已知向量与 b 不共线"):\n            pass\n'
    assert voiceovers(source) == [{"line": 3, "text": "已知向量与 b 不共线"}]


def test_model_quotes_must_match_actual_source_and_asr():
    lines = [{"line": 10, "text": "已知向量与 b 不共线"}]
    source_issues = [
        {"line": 10, "source_quote": "向量与 b 不共线"},
        {"line": 10, "source_quote": "A 与 B 不共线"},
    ]
    valid, rejected = _validate_source(source_issues, lines)
    assert len(valid) == 1 and rejected == 1


def test_spoken_equivalence_and_source_omission_direction():
    assert _spoken_canonical("解得 j 等于负一") == _spoken_canonical("解得 J 等于-1")
    assert _spoken_canonical("法向量 n 二") == _spoken_canonical("法向量 N2")
    assert _asr_adds_only("已知向量与 b 不共线", "已知向量 a 与 b 不共线")

    lines = [{"line": 10, "text": "已知向量 a 与 b 不共线"}]
    segments = [{"start_ms": 1000, "end_ms": 2300, "text": "已知向量与B不共线"}]
    audio_issues = [
        {"source_quote": "向量 a 与 b", "asr_quote": "向量与B", "segment_index": 1},
        {"source_quote": "不存在", "asr_quote": "向量与B", "segment_index": 1},
    ]
    valid, rejected = _validate_audio(audio_issues, lines, segments)
    assert valid[0]["start_ms"] == 1000
    assert len(valid) == 1 and rejected == 1


def test_self_negating_source_review_cannot_hide_real_audio_difference():
    assert not actionable_source_issue({
        "category": "source_wrong_expression", "confidence": "high",
        "source_quote": "用三十八减五得到三十三",
        "why": "三十八减五本身正确，无错误。",
    })
    assert actionable_source_issue({
        "category": "source_missing_object", "confidence": "high",
        "source_quote": "已知向量与 b 不共线", "why": "缺少变量 a。",
    })
