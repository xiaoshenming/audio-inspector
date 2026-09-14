"""Resumable batch runner for the transcript inspection lane."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from . import analyzer
from .expected_text import extract_expected_voiceover
from .report import write_report


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise TypeError("manifest must be a JSON list or an object with an items list")
    result = []
    seen = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise TypeError(f"manifest item {index} is not an object")
        item_id = str(raw.get("item_id") or "").strip()
        video_path = Path(str(raw.get("video_path") or "")).expanduser().resolve()
        if not item_id or item_id in seen:
            raise ValueError(f"missing or duplicate item_id at item {index}")
        if not video_path.is_file():
            raise ValueError(f"video not found for {item_id}: {video_path}")
        seen.add(item_id)
        result.append({**raw, "item_id": item_id, "video_path": str(video_path)})
    return result


def expected_text(record: dict[str, Any]) -> str:
    direct = str(record.get("expected_text") or "").strip()
    if direct:
        return direct
    text_path = str(record.get("expected_text_path") or "").strip()
    if text_path:
        return Path(text_path).expanduser().read_text(encoding="utf-8")
    source_path = str(record.get("source_path") or "").strip()
    if source_path:
        return extract_expected_voiceover(
            Path(source_path).expanduser().read_text(encoding="utf-8")
        )
    return ""


def run_batch(
    manifest: Path,
    output: Path,
    *,
    model: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    concurrency: int = 1,
    model_workers: int = 1,
    limit: int | None = None,
) -> dict[str, Any]:
    from faster_whisper import WhisperModel  # type: ignore

    if concurrency < 1 or model_workers < 1:
        raise ValueError("concurrency and model_workers must be positive")
    records = load_manifest(manifest)
    if limit is not None:
        records = records[: max(0, limit)]
    output.mkdir(parents=True, exist_ok=True)
    items_dir = output / "items"
    items_dir.mkdir(exist_ok=True)
    model_options = {
        "device": device,
        "compute_type": compute_type,
        "num_workers": model_workers,
    }
    if device == "cpu":
        model_options["cpu_threads"] = 1
    analyzer._MODEL = WhisperModel(model, **model_options)
    analyzer._MODEL_NAME = model
    started = time.time()

    def inspect(record: dict[str, Any]) -> dict[str, Any]:
        name = hashlib.sha256(record["item_id"].encode()).hexdigest()[:24] + ".json"
        target = items_dir / name
        if target.is_file():
            return json.loads(target.read_text(encoding="utf-8"))
        item_started = time.time()
        try:
            payload, evidence = analyzer.analyze_video(
                record["video_path"],
                expected_text=expected_text(record),
                model_name=model,
            )
            result = {
                "status": "completed",
                "item": record,
                "elapsed_seconds": round(time.time() - item_started, 3),
                "payload": payload,
                "evidence": evidence,
            }
        except Exception as exc:  # noqa: BLE001 - one bad input must not erase the batch.
            result = {
                "status": "failed_open",
                "item": record,
                "elapsed_seconds": round(time.time() - item_started, 3),
                "error": f"{type(exc).__name__}: {exc}"[:1000],
            }
        atomic_json(target, result)
        return result

    completed: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(inspect, record) for record in records]
        for future in concurrent.futures.as_completed(futures):
            completed.append(future.result())
            atomic_json(output / "progress.json", _summary(completed, records, started))
    summary = _summary(completed, records, started)
    summary["items"] = sorted(completed, key=lambda row: row["item"]["item_id"])
    atomic_json(output / "summary.json", summary)
    write_report(output / "report.html", summary)
    return summary


def _summary(completed: list[dict], records: list[dict], started: float) -> dict:
    return {
        "schema_version": "audio-inspector.batch.v1",
        "pid": os.getpid(),
        "total": len(records),
        "completed": len(completed),
        "succeeded": sum(row["status"] == "completed" for row in completed),
        "failed_open": sum(row["status"] == "failed_open" for row in completed),
        "candidate_videos": sum(
            bool(row.get("payload", {}).get("summary", {}).get("visible_risk_count"))
            for row in completed
        ),
        "elapsed_seconds": round(time.time() - started, 3),
    }
