"""单视频 faster-whisper 分析器；模型在独立 observer 进程内常驻。"""

from __future__ import annotations

import subprocess
import time
from typing import Any

from .contract import completed_payload
from .decision import decide
from .transcript_evidence import mismatch_finding as _mismatch_finding
from .transcript_evidence import segment_findings as _segment_findings

_MODEL: Any = None
_MODEL_NAME = ""
DETECTOR_VERSION = "3.0.0"


def analyze_video(
    video_path: str,
    *,
    expected_text: str = "",
    model_name: str = "small",
    max_findings: int = 100,
    pronunciation_manifest: dict | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model, load_ms = _model(model_name)
    started = time.perf_counter()
    segments_iter, info = model.transcribe(
        video_path,
        language="zh",
        vad_filter=True,
        word_timestamps=False,
        initial_prompt="请使用简体中文转写；数学字母、数字和符号按实际读音记录。",
    )
    segments = [
        {"start": float(item.start), "end": float(item.end), "text": str(item.text).strip()}
        for item in segments_iter
    ]
    inference_ms = round((time.perf_counter() - started) * 1000)
    duration_ms = round(float(getattr(info, "duration", 0.0) or _duration(video_path)) * 1000)
    findings = _segment_findings(segments)
    mismatch = _mismatch_finding(expected_text, segments)
    if mismatch:
        findings.insert(0, mismatch)
    required_lanes = ["transcript"]
    completed_lanes = ["transcript"]
    lane_evidence: list[dict[str, Any]] = []
    if pronunciation_manifest and pronunciation_manifest.get("entries"):
        required_lanes.append("pronunciation")
        try:
            from .mfa_runner import analyze_pronunciation

            pronunciation_findings, pronunciation_evidence = analyze_pronunciation(
                video_path,
                expected_text=expected_text,
                manifest=pronunciation_manifest,
            )
            findings.extend(pronunciation_findings)
            lane_evidence.append(pronunciation_evidence)
            completed_lanes.append("pronunciation")
        except Exception as exc:  # noqa: BLE001 - lane failure is review evidence.
            lane_evidence.append({
                "lane": "pronunciation",
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}"[:1000],
            })
    payload, evidence = completed_payload(
        model=f"faster-whisper-{model_name}",
        audio_duration_ms=duration_ms,
        inference_ms=inference_ms,
        model_load_ms=load_ms,
        findings=findings[:max_findings],
    )
    payload["detector_version"] = DETECTOR_VERSION
    payload["decision"] = decide(
        findings,
        required_lanes=required_lanes,
        completed_lanes=completed_lanes,
    )
    evidence["transcript_segments"] = segments
    evidence["lanes"] = lane_evidence
    return payload, evidence


def _model(model_name: str) -> tuple[Any, int]:
    global _MODEL, _MODEL_NAME
    if _MODEL is not None and _MODEL_NAME == model_name:
        return _MODEL, 0
    from faster_whisper import WhisperModel  # type: ignore

    started = time.perf_counter()
    _MODEL = WhisperModel(model_name, device="cpu", compute_type="int8")
    _MODEL_NAME = model_name
    return _MODEL, round((time.perf_counter() - started) * 1000)


def _duration(video_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", video_path],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0
