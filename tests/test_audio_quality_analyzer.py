import json
from collections import defaultdict
from pathlib import Path

from audio_inspector.analyzer import _mismatch_finding, _segment_findings


def test_segment_findings_keep_geometry_letters_record_only():
    findings = _segment_findings([{"start": 1.0, "end": 2.0, "text": "连接 A B C 三点"}])
    assert [(item["type"], item["severity"]) for item in findings] == [
        ("stt_latin_token", "low")
    ]


def test_segment_findings_surface_prime_and_vector_reading():
    findings = _segment_findings([
        {"start": 3.0, "end": 5.0, "text": "连接 A prime 并沿向量微平移"}
    ])
    assert [(item["type"], item["severity"]) for item in findings] == [
        ("stt_latin_token", "low")
    ]


def test_mismatch_requires_expected_text_and_low_similarity():
    segments = [{"start": 0.0, "end": 1.0, "text": "完全不同内容"}]
    assert _mismatch_finding("三角形中线交于重心", segments)["type"] == "script_transcript_mismatch"
    assert _mismatch_finding("", segments) is None


def test_synthetic_mismatch_dataset_keeps_non_risk_cases_below_visible_level():
    fixture = Path(__file__).with_name("fixtures") / "audio_quality_synthetic_cases.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    metrics = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    for case in cases:
        segments = [{"start": 4.0, "end": 6.0, "text": case["transcript"]}]
        result = _mismatch_finding(case["expected"], segments)
        detected = bool(result and result["severity"] in {"high", "medium"})
        bucket = metrics[case["category"]]
        bucket["tp" if detected and case["risk"] else
               "fp" if detected else "fn" if case["risk"] else "tn"] += 1
    assert sum(item["fp"] for item in metrics.values()) == 0, metrics


def test_homophone_transcription_difference_is_ignored():
    expected = "我们先观察图像的变化，然后连接辅助线并证明两个角相等。"
    transcript = "我们先观察图像的变化，然后连接辅助县并证明两个角相等。"
    assert _mismatch_finding(expected, [{"start": 8.0, "end": 11.0, "text": transcript}]) is None
