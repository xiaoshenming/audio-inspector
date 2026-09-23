"""Run a second ASR model on bounded clips without feeding it expected text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def transcribe(dataset: Path, output: Path, model_path: str) -> dict:
    rows = json.loads((dataset / "clips.json").read_text())["items"]
    items = output / "items"
    items.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(model_path, device="cpu", compute_type="int8", cpu_threads=4)
    completed = failed = 0
    for index, row in enumerate(rows, 1):
        target = items / f"{row['item_id']}-{row['cue_index']}.json"
        if target.is_file():
            previous = json.loads(target.read_text())
            if previous.get("status") == "completed":
                completed += 1
                continue
        try:
            spans, info = model.transcribe(str(dataset / row["clip"]), language="zh",
                                           vad_filter=False, condition_on_previous_text=False)
            segments = [{"start_seconds": float(part.start),
                         "end_seconds": float(part.end), "text": part.text.strip()}
                        for part in spans]
            result = {"status": "completed", "item_id": row["item_id"],
                      "cue_index": row["cue_index"],
                      "text": "".join(part["text"] for part in segments),
                      "segments": segments, "duration_seconds": float(info.duration)}
            completed += 1
        except Exception as exc:  # noqa: BLE001 - do not hide failed clips.
            result = {"status": "failed_open", "item_id": row["item_id"],
                      "cue_index": row["cue_index"],
                      "error": f"{type(exc).__name__}: {exc}"[:300]}
            failed += 1
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        if index % 10 == 0 or index == len(rows):
            print(f"independent_asr {index}/{len(rows)} failed={failed}", flush=True)
    summary = {"clips": len(rows), "completed": completed, "failed_open": failed,
               "model": model_path}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False,
                                             indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    print(json.dumps(transcribe(args.dataset, args.output, args.model),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
