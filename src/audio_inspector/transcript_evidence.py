"""从转写中提取通用、非确认性的审查证据。"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any

from .contract import finding
from .text_normalization import comparison_text, phonetic_replacement_equal


def segment_findings(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for segment in segments:
        tokens = re.findall(r"(?<![A-Za-z])[A-Za-z]+(?![A-Za-z])", str(segment["text"]))
        if tokens:
            results.append(_segment_item(segment, "stt_latin_token", "转写包含拉丁词，保留待复核", tokens[:12]))
    return results


def mismatch_finding(expected: str, segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    transcript = "".join(str(item["text"]) for item in segments)
    if not expected or not transcript:
        return None
    expected_compared = comparison_text(expected)
    actual_compared = comparison_text(transcript)
    matcher = SequenceMatcher(None, expected_compared, actual_compared)
    raw_edits = [
        (tag, expected_compared[i1:i2], actual_compared[j1:j2], j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]
    edits = [item for item in raw_edits if not phonetic_replacement_equal(item[0], item[1], item[2])]
    if not edits:
        return None
    _tag, _before, _after, actual_index = edits[0]
    located = _segment_at_character(segments, actual_index)
    summaries = [_edit_summary(item[0], item[1], item[2]) for item in edits]
    score = matcher.ratio()
    return finding(
        finding_id=hashlib.sha1(f"mismatch:{score:.3f}:{expected[:100]}".encode()).hexdigest()[:20],
        finding_type="script_transcript_mismatch",
        severity="low",
        start=located["start"],
        end=located["end"],
        transcript=transcript[:500],
        reason=f"脚本与转写存在差异，保留待复核：{summaries[0]}",
        details={
            "similarity": round(score, 3),
            "edits": summaries[:12],
            "phonetic_edits_ignored": len(raw_edits) - len(edits),
            "evidence_scope": "candidate_only",
        },
    )


def _segment_item(segment: dict[str, Any], kind: str, reason: str, tokens: list[str]) -> dict[str, Any]:
    seed = f"{kind}:{segment['start']}:{segment['text']}"
    return finding(
        finding_id=hashlib.sha1(seed.encode()).hexdigest()[:20],
        finding_type=kind,
        severity="low",
        start=segment["start"],
        end=segment["end"],
        transcript=segment["text"],
        reason=reason,
        details={"tokens": tokens, "evidence_scope": "candidate_only"},
    )


def _edit_summary(tag: str, expected: str, actual: str) -> str:
    labels = {"replace": "替换", "delete": "缺词", "insert": "多词"}
    return f"{labels.get(tag, tag)}：原文“{expected or '∅'}”，识别“{actual or '∅'}”"


def _segment_at_character(segments: list[dict[str, Any]], index: int) -> dict[str, Any]:
    offset = 0
    for segment in segments:
        offset += len(comparison_text(str(segment["text"])))
        if index < offset:
            return segment
    return segments[-1] if segments else {"start": 0.0, "end": 0.0, "text": ""}
