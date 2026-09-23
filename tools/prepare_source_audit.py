"""Freeze question context and narration lines for a blind second source review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev_pb2.semantic_review import _context, voiceovers


def prepare(manifest: Path, questions: Path, output: Path) -> dict:
    rows = json.loads(manifest.read_text())["items"]
    contexts = json.loads(questions.read_text())
    payload = {"items": [{"item_id": row["item_id"],
                          "question_context": _context(contexts.get(row["item_id"])),
                          "voiceovers": voiceovers(Path(row["source_path"]).read_text())}
                         for row in rows]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {"videos": len(rows),
            "voiceovers": sum(len(row["voiceovers"]) for row in payload["items"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.manifest, args.questions, args.output),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
