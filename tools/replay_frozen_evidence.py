"""Replay updated source/literal checks over frozen original media evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev_pb2.literal_reading import detect_one
from dev_pb2.semantic_review import _context, voiceovers
from dev_pb2.source_patterns import missing_set_label


def _items(directory: Path) -> dict[str, dict]:
    result = {}
    for path in (directory / "items").glob("*.json"):
        row = json.loads(path.read_text())
        result[row["item_id"]] = row
    return result


def replay(dataset: Path, output: Path) -> dict:
    manifest = json.loads((dataset / "manifest.json").read_text())["items"]
    existing = {row["item_id"] for row in json.loads(
        (dataset / "screening-review/candidates.json").read_text())}
    literal_asr = _items(dataset / "literal-asr-targeted")
    questions = json.loads((dataset / "metadata/questions.json").read_text())
    newly_flagged = []
    missing_literal_evidence = []
    for row in manifest:
        if row["item_id"] in existing:
            continue
        item_id = row["item_id"]
        lines = voiceovers(Path(row["source_path"]).read_text(encoding="utf-8"))
        source = missing_set_label(lines, _context(questions.get(item_id)))
        evidence = literal_asr.get(item_id) or {}
        if evidence.get("status") != "completed":
            missing_literal_evidence.append(item_id)
        literal = detect_one(row, evidence) if evidence.get("status") == "completed" else []
        if source or literal:
            newly_flagged.append({"item_id": item_id, "source_issues": source,
                                  "literal_issues": literal})
    result = {"original_candidates": len(existing),
              "new_videos": len(newly_flagged),
              "updated_candidate_count": len(existing) + len(newly_flagged),
              "new_source_videos": sum(bool(row["source_issues"])
                                       for row in newly_flagged),
              "new_literal_videos": sum(bool(row["literal_issues"])
                                        for row in newly_flagged),
              "missing_literal_evidence": missing_literal_evidence,
              "newly_flagged": newly_flagged}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return {key: result[key] for key in
            ("original_candidates", "new_videos", "updated_candidate_count",
             "new_source_videos", "new_literal_videos")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.dataset, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
