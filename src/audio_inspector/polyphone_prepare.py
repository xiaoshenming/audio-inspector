"""在声学模型就绪前准备多音字候选与时间轴。"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from .polyphone_batch_inputs import (
    build_candidates,
    load_expected_text,
    load_timeline,
)


def run(args: argparse.Namespace) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    results = args.output / "prepared.jsonl"
    completed = _completed(results)
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise TypeError("manifest must be a JSON list or an object with an items list")
    if args.limit:
        items = items[:args.limit]

    from g2pw import G2PWConverter

    g2pw = G2PWConverter(
        model_dir=str(args.g2pw_model),
        style="pinyin",
        model_source=str(args.g2pw_tokenizer),
        num_workers=0,
        batch_size=32,
        turnoff_tqdm=True,
    )
    started = time.time()
    risk_phrases = _load_risk_phrases(args.lexicon)
    prepared = len(completed)
    failed = 0
    candidates = 0
    for position, item in enumerate(items, 1):
        item_id = str(item["item_id"])
        if item_id in completed:
            continue
        try:
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
            found = build_candidates(
                text, timeline, readings,
                ignored_chars=set(args.ignore_chars),
                risk_phrases=risk_phrases,
            )
            payload = {
                "item_id": item_id,
                "status": "prepared",
                "item": item,
                "candidates": [asdict(candidate) for candidate in found],
            }
            prepared += 1
            candidates += len(found)
        except Exception as error:  # noqa: BLE001 - batch isolates per-item failures.
            payload = {
                "item_id": item_id,
                "status": "processing_failed",
                "item": item,
                "error": f"{type(error).__name__}: {error}",
                "candidates": [],
            }
            failed += 1
        _append(results, payload)
        _progress(
            args.output, position, len(items), prepared, failed,
            candidates, started,
        )
        print(
            f"prepared={position}/{len(items)} candidates={candidates} failed={failed}",
            flush=True,
        )


def _completed(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    values = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            values.add(str(json.loads(line)["item_id"]))
        except (KeyError, json.JSONDecodeError):
            continue
    return values


def _append(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _progress(output, position, total, prepared, failed, candidates, started) -> None:
    payload = {
        "position": position, "total": total, "prepared": prepared,
        "failed": failed, "candidates": candidates,
        "elapsed_seconds": round(time.time() - started, 3),
        "updated_at": time.time(),
    }
    path = output / "prepare-progress.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    temporary.replace(path)


def _load_risk_phrases(path: Path | None) -> dict[str, tuple[str, ...]]:
    if not path:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(key): tuple(str(value).split())
        for item in payload.get("pronunciation", [])
        for key, value in item.items()
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--g2pw-model", type=Path, required=True)
    parser.add_argument("--g2pw-tokenizer", type=Path, required=True)
    parser.add_argument("--stt-items", type=Path, action="append", default=[])
    parser.add_argument("--ignore-chars", default="")
    parser.add_argument("--lexicon", type=Path)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
