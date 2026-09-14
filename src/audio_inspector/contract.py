"""STT 观测结果的稳定、可留存合同。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "audio-inspector.result.v1"
MAX_FINDINGS = 100


def finding(
    *,
    finding_id: str,
    finding_type: str,
    severity: str,
    start: float | None,
    end: float | None,
    transcript: str,
    reason: str,
    decision: str = "candidate",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "finding_id": _text(finding_id, 160),
        "type": _text(finding_type, 80),
        "severity": severity if severity in {"high", "medium", "low"} else "low",
        "decision": decision if decision in {"candidate", "confirmed"} else "candidate",
        "review_state": "unreviewed",
        "start_ms": _millis(start),
        "end_ms": _millis(end),
        "transcript_text": _text(transcript, 500),
        "reason": _text(reason, 500),
        "details": _safe_mapping(details or {}),
    }


def completed_payload(
    *,
    model: str,
    audio_duration_ms: int,
    inference_ms: int,
    model_load_ms: int,
    findings: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    retained = findings[:MAX_FINDINGS]
    counts = {"high": 0, "medium": 0, "low": 0}
    for item in retained:
        counts[str(item.get("severity") or "low")] += 1
    confirmed = sum(item.get("decision") == "confirmed" for item in retained)
    candidate_risk = sum(
        item.get("decision", "candidate") == "candidate"
        and item.get("severity") in {"high", "medium"}
        for item in retained
    )
    summary = {
        "confirmed_issue_count": confirmed,
        "candidate_risk_count": candidate_risk,
        "visible_risk_count": counts["high"] + counts["medium"],
        "record_only_count": counts["low"],
        **counts,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "fail_open": False,
        "model": _text(model, 120),
        "audio_duration_ms": max(0, int(audio_duration_ms)),
        "inference_ms": max(0, int(inference_ms)),
        "model_load_ms": max(0, int(model_load_ms)),
        "real_time_factor": round(inference_ms / audio_duration_ms, 4)
        if audio_duration_ms else None,
        "summary": summary,
    }
    return payload, {"findings": retained, "finding_count": len(findings)}


def failed_payload(error: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "failed_open",
        "fail_open": True,
        "error": _text(error, 1000),
        "summary": {
            "confirmed_issue_count": 0,
            "candidate_risk_count": 0,
            "visible_risk_count": 0,
            "record_only_count": 0,
        },
    }


def _millis(value: float | None) -> int | None:
    return max(0, round(float(value) * 1000)) if value is not None else None


def _text(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "")[:limit]


def _safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in list(value.items())[:20]:
        if item is None or isinstance(item, (bool, int, float)):
            safe[_text(key, 80)] = item
        elif isinstance(item, str):
            safe[_text(key, 80)] = _text(item, 300)
        elif isinstance(item, list):
            safe[_text(key, 80)] = [_text(entry, 120) for entry in item[:20]]
    return safe
