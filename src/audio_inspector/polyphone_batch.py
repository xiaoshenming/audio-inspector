"""通用多音字批量声学核验，逐项落盘并支持断点续跑。"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .phonetic_ctc import PhoneticCtc
from .polyphone_acoustic import score_video
from .polyphone_batch_inputs import (
    Candidate,
    build_candidates,
    load_expected_text,
    load_timeline,
)


def run(args: argparse.Namespace) -> None:
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    results_path = output / "results.jsonl"
    completed = _completed_ids(results_path)
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise TypeError("manifest must be a JSON list or an object with an items list")
    if args.limit:
        items = items[:args.limit]
    _write_json(output / "host-check.json", _host_check(args, len(items)))

    prepared = _load_prepared(args.prepared) if args.prepared else {}
    g2pw = None
    if not prepared:
        from g2pw import G2PWConverter

        g2pw = G2PWConverter(
            model_dir=str(args.g2pw_model),
            style="pinyin",
            model_source=str(args.g2pw_tokenizer),
            num_workers=0,
            batch_size=32,
            turnoff_tqdm=True,
        )
    risk_phrases = _load_risk_phrases(args.lexicon)
    engine = PhoneticCtc(args.phonetic_model, device="cpu")
    started = time.time()
    counters = {"completed": len(completed), "failed": 0, "candidates": 0,
                "confirmed_issue": 0, "uncertain": 0, "passed": 0}
    for position, item in enumerate(items, 1):
        item_id = str(item["item_id"])
        if item_id in completed:
            continue
        try:
            result = _process_item(
                item, args, g2pw, engine, prepared.get(item_id), risk_phrases,
            )
            for finding in result["findings"]:
                counters[finding["status"]] += 1
            counters["candidates"] += len(result["findings"])
            counters["completed"] += 1
        except Exception as error:  # noqa: BLE001 - batch isolates per-item failures.
            result = {
                "item_id": item_id,
                "status": "processing_failed",
                "error": f"{type(error).__name__}: {error}",
                "item": item,
                "findings": [],
            }
            counters["failed"] += 1
        _append_jsonl(results_path, result)
        _progress(output, counters, position, len(items), started)
        print(
            f"processed={position}/{len(items)} candidates={counters['candidates']} "
            f"issues={counters['confirmed_issue']} failed={counters['failed']}",
            flush=True,
        )
    _progress(output, counters, len(items), len(items), started, finished=True)


def _process_item(
    item: dict, args, g2pw, engine: PhoneticCtc, prepared, risk_phrases: set[str],
) -> dict:
    if prepared:
        if prepared["status"] != "prepared":
            raise ValueError(prepared.get("error") or "candidate preparation failed")
        candidates = [Candidate(**raw) for raw in prepared["candidates"]]
    else:
        source = Path(item["source_path"])
        subtitle_raw = str(item.get("subtitle_path") or "")
        subtitle = Path(subtitle_raw) if subtitle_raw else None
        text = load_expected_text(source, subtitle)
        if not text:
            raise ValueError("expected text unavailable")
        timeline = load_timeline(item, args.stt_items)
        if not timeline:
            raise ValueError("subtitle/STT timeline unavailable")
        readings = g2pw(text)[0]
        candidates = build_candidates(
            text, timeline, readings, ignored_chars=set(args.ignore_chars),
            risk_phrases=risk_phrases,
        )
    if args.max_candidates:
        candidates = candidates[:args.max_candidates]
    findings = score_video(
        Path(item["video_path"]), candidates, engine,
        batch_size=args.batch_size,
    )
    return {
        "schema_version": "audio-inspector.polyphone-result.v1",
        "item_id": item["item_id"],
        "status": "completed",
        "item": item,
        "candidate_count": len(findings),
        "findings": findings,
    }


def _host_check(args, total: int) -> dict:
    import torch

    return {
        "schema_version": "audio-inspector.polyphone-host-check.v1",
        "host": os.uname().nodename,
        "cpu_count": os.cpu_count(),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "device": "cpu",
        "total_items": total,
        "batch_size": args.batch_size,
        "manifest": str(args.manifest),
        "phonetic_model": str(args.phonetic_model),
        "g2pw_model": str(args.g2pw_model),
        "g2pw_tokenizer": str(args.g2pw_tokenizer),
    }


def _completed_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    completed = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            completed.add(str(json.loads(line)["item_id"]))
        except (KeyError, json.JSONDecodeError):
            continue
    return completed


def _load_prepared(path: Path | None) -> dict[str, dict]:
    if not path:
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        values[str(payload["item_id"])] = payload
    return values


def _load_risk_phrases(path: Path | None) -> dict[str, tuple[str, ...]]:
    if not path:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(key): tuple(str(value).split())
        for item in payload.get("pronunciation", [])
        for key, value in item.items()
    }


def _append_jsonl(path: Path, value: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _progress(output, counters, position, total, started, *, finished=False) -> None:
    elapsed = max(0.001, time.time() - started)
    payload = dict(counters)
    payload.update({
        "position": position, "total": total,
        "elapsed_seconds": round(elapsed, 3),
        "items_per_minute": round(max(0, position) / elapsed * 60, 3),
        "finished": finished, "updated_at": time.time(),
    })
    _write_json(output / "progress.json", payload)


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phonetic-model", type=Path, required=True)
    parser.add_argument("--g2pw-model", type=Path, required=True)
    parser.add_argument("--g2pw-tokenizer", type=Path, required=True)
    parser.add_argument("--stt-items", type=Path, action="append", default=[])
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--lexicon", type=Path)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--ignore-chars", default="")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-candidates", type=int)
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
