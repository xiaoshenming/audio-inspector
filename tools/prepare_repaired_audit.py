"""Freeze inputs for an independent audit of machine-clean repaired videos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev_pb2.semantic_review import voiceovers


def prepare(batch: Path, summary: Path, output: Path) -> dict:
    cases = {row["request"]["item_id"]: row for row in
             json.loads(batch.read_text())["cases"]}
    rows = [row for row in json.loads(summary.read_text())["rows"]
            if row["final"] == "machine_clean"]
    media = []
    source = []
    requests = output / "requests"
    requests.mkdir(parents=True, exist_ok=True)
    for row in rows:
        video = Path(row["video_path"])
        receipt_file = video.parent / ("receipt.json" if video.parent.name == "worker-render"
                                       else "repair-receipt.json")
        receipt = json.loads(receipt_file.read_text())
        item_id = row["item_id"]
        record = {"item_id": item_id, "video_path": str(video),
                  "source_path": receipt["source_path"],
                  "subtitle_path": receipt["subtitle_path"]}
        media.append(record)
        video_sha = receipt["video_sha256"]
        source_sha = receipt["source_sha256"]
        request = {**record, "revision_id": "independent-audit:" + video_sha[:12],
                   "video_sha256": video_sha, "source_sha256": source_sha,
                   "question": cases[item_id]["request"].get("question") or {}}
        (requests / f"{item_id}.json").write_text(json.dumps(
            request, ensure_ascii=False, indent=2) + "\n")
        source.append({"item_id": item_id,
                       "question_context": cases[item_id]["request"].get("question") or {},
                       "voiceovers": voiceovers(Path(receipt["source_path"]).read_text())})
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(json.dumps({"items": media},
                                              ensure_ascii=False, indent=2) + "\n")
    (output / "source-context.json").write_text(json.dumps({"items": source},
                                                    ensure_ascii=False, indent=2) + "\n")
    return {"videos": len(media), "source_lines": sum(len(row["voiceovers"])
                                                    for row in source)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.batch, args.summary, args.output),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
