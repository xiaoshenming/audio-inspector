"""多证据的三态裁决；不把不确定样本硬塞进通过或失败。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def decide(
    findings: Iterable[Mapping[str, object]],
    *,
    required_lanes: Iterable[str],
    completed_lanes: Iterable[str],
) -> dict[str, object]:
    rows = list(findings)
    required = set(required_lanes)
    completed = set(completed_lanes)
    confirmed = [row for row in rows if row.get("decision") == "confirmed"]
    review = [
        row for row in rows
        if row.get("decision") != "confirmed"
        and row.get("severity") in {"high", "medium"}
    ]
    missing = sorted(required - completed)
    if confirmed:
        verdict = "confirmed_issue"
    elif review or missing:
        verdict = "needs_review"
    else:
        verdict = "passed"
    return {
        "verdict": verdict,
        "confirmed_issue_count": len(confirmed),
        "review_candidate_count": len(review),
        "missing_lanes": missing,
        "evidence_only": True,
    }
