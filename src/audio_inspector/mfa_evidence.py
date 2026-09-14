"""将 MFA 全句音素对齐结果与生成前发音清单比较。"""

from __future__ import annotations

import re
from pathlib import Path

from .contract import finding


def compare_manifest(textgrid: Path, manifest: dict) -> list[dict]:
    words, phones = _tiers(textgrid.read_text(encoding="utf-8"))
    results = []
    for entry_index, entry in enumerate(manifest.get("entries", [])):
        text = str(entry.get("text") or "")
        expected = tuple(str(phone) for phone in entry.get("phones", []))
        matches = [(start, end) for start, end, word in words if word == text]
        if not matches:
            results.append(_review_finding(entry_index, text, "对齐结果中未找到清单短语"))
            continue
        for occurrence, (start, end) in enumerate(matches):
            observed = tuple(
                phone for p_start, p_end, phone in phones
                if phone not in {"", "sil", "sp", "<eps>"}
                and p_start >= start - 0.001 and p_end <= end + 0.001
            )
            if "spn" in observed:
                results.append(_review_finding(
                    entry_index, text, "声学对齐无法解析该短语", start, end, occurrence
                ))
            elif observed != expected:
                results.append(finding(
                    finding_id=f"pronunciation:{entry_index}:{occurrence}",
                    finding_type="pronunciation_mismatch",
                    severity="high",
                    decision="confirmed",
                    start=start,
                    end=end,
                    transcript=text,
                    reason="实际音素与生成前确认的发音清单不一致",
                    details={
                        "expected_phones": list(expected),
                        "observed_phones": list(observed),
                        "manifest_source": str(entry.get("source") or ""),
                    },
                ))
    return results


def _review_finding(
    entry_index: int,
    text: str,
    reason: str,
    start: float | None = None,
    end: float | None = None,
    occurrence: int = 0,
) -> dict:
    return finding(
        finding_id=f"pronunciation-review:{entry_index}:{occurrence}",
        finding_type="pronunciation_alignment_uncertain",
        severity="medium",
        start=start,
        end=end,
        transcript=text,
        reason=reason,
        details={"evidence_scope": "review_required"},
    )


def _tiers(content: str) -> tuple[list[tuple], list[tuple]]:
    parsed = {}
    for part in content.split('name = "')[1:]:
        name = part.split('"', 1)[0]
        parsed[name] = [
            (float(start), float(end), text)
            for start, end, text in re.findall(
                r'xmin = ([\d.]+)\s+xmax = ([\d.]+)\s+text = "([^"]*)"', part
            )
        ]
    return parsed.get("words", []), parsed.get("phones", [])
