import json
from pathlib import Path

from audio_inspector.polyphone_acoustic import _isolate_occurrences
from audio_inspector.polyphone_batch_inputs import (
    Candidate,
    TimelineChar,
    align_timeline,
    build_candidates,
    parse_vtt,
)
from audio_inspector.polyphone_report import generate


def test_parse_vtt_spreads_characters_over_cue(tmp_path: Path) -> None:
    path = tmp_path / "sample.vtt"
    path.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n米尺有多长。\n",
        encoding="utf-8",
    )
    timeline = parse_vtt(path)
    assert "".join(item.char for item in timeline) == "米尺有多长"
    assert timeline[0].start == 1.0
    assert timeline[-1].end == 3.0


def test_alignment_keeps_equal_characters_across_stt_error() -> None:
    timeline = [TimelineChar(char, index, index + 1) for index, char in enumerate("米尺有多常")]
    assert set(align_timeline("米尺有多长", timeline)) == {0, 1, 2, 3}


def test_build_candidates_uses_context_reading() -> None:
    text = "米尺有多长"
    timeline = [TimelineChar(char, index, index + 1) for index, char in enumerate(text)]
    readings = [None] * len(text)
    readings[text.index("长")] = "chang2"
    candidates = build_candidates(
        text, timeline, readings, ignored_chars=set(),
        risk_phrases={"多长": ("duo1", "chang2")},
    )
    assert [item.char for item in candidates] == ["长"]
    assert "zhang3" in candidates[0].alternative_pinyin


def test_isolate_repeated_character_readings_in_cue_order() -> None:
    candidates = [Candidate(
        index, "分", "", "fen4", ("fen1",), 60.0, 73.0, True,
        span_char_ordinal=ordinal,
    ) for ordinal, index in enumerate((10, 20, 30, 40))]
    metadata = [{"expected": "ㄈㄣ4", "alternatives": ["ㄈㄣ1"]} for _ in candidates]
    observed = {
        f"{index}:main": "ㄈㄣ4ㄌㄧㄤ4ㄈㄣ1ㄒㄧ1ㄈㄣ1ㄌㄧㄤ4ㄈㄣ1ㄌㄧㄤ4"
        for index in range(4)
    }
    _isolate_occurrences(candidates, metadata, observed, ("main",))
    assert [observed[f"{index}:main"] for index in range(4)] == [
        "ㄈㄣ4", "ㄈㄣ1", "ㄈㄣ1", "ㄈㄣ1",
    ]


def test_report_escapes_context_and_uses_allowlisted_media_route(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps({
        "item_id": "group/sample",
        "status": "completed",
        "candidate_count": 1,
        "item": {"template": "group", "video_id": "sample"},
        "findings": [{
            "status": "confirmed_issue", "char": "长",
            "context": "多长<script>", "start": 12.5,
            "expected_pinyin": "chang2",
            "alternative_pinyin": ["zhang3"],
            "alternative_zhuyin": ["ㄓㄤ3"],
            "observed_alternative": "ㄓㄤ3",
            "observed_windows": ["ㄓㄤ3", "ㄓㄤ3", "ㄔㄤ2"],
        }],
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    output = tmp_path / "report.html"
    summary = generate(results, output, title="测试报告")
    page = output.read_text(encoding="utf-8")
    assert summary["confirmed_issue"] == 1
    assert "/media?item=" in page
    assert "多长&lt;script&gt;" in page
