"""Package a frozen 152-video shortlist as isolated module batch inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _context(raw: object) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {"question": raw}
    if not isinstance(raw, dict):
        return {}
    return {key: str(raw[key])[:5000] for key in
            ("question", "problem_text", "solution_steps", "final_answer")
            if raw.get(key)}


def build(dataset: Path, output: Path, destination_root: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    candidates = json.loads((dataset / "screening-review/candidates.json").read_text())
    questions = json.loads((dataset / "metadata/questions.json").read_text())
    inventory = json.loads((dataset / "metadata/inventory.json").read_text())["rows"]
    inventory_by_item = {row["item_id"]: row for row in inventory}
    cases = []
    for candidate in candidates:
        item_id = candidate["item_id"]
        folder = output / "cases" / item_id
        folder.mkdir(parents=True, exist_ok=True)
        files = {"video": dataset / "videos" / f"{item_id}.mp4",
                 "unburned": dataset / "videos" / f"{item_id}.unburned.mp4",
                 "source": dataset / "sources" / f"{item_id}.py",
                 "source_pack": dataset / "sources" / f"{item_id}.tar",
                 "subtitle": dataset / "subtitles" / f"{item_id}.srt"}
        names = {"video": "original.mp4", "unburned": "unburned.mp4",
                 "source": "main.py", "source_pack": "source.tar",
                 "subtitle": "original.srt"}
        for key, original in files.items():
            if original.is_file():
                target = folder / names[key]
                if not target.is_file() or target.stat().st_size != original.stat().st_size:
                    shutil.copy2(original, target)
        remote = destination_root / "cases" / item_id
        info = inventory_by_item[item_id]
        request = {"item_id": item_id,
                   "revision_id": "completion:" + info["completion_id"],
                   "video_path": str(remote / names["video"]),
                   "source_path": str(remote / names["source"]),
                   "subtitle_path": str(remote / names["subtitle"]),
                   "question": _context(questions.get(item_id)),
                   "video_sha256": _digest(files["video"]),
                   "source_sha256": _digest(files["source"])}
        cases.append({"request": request,
                      "unburned": str(remote / names["unburned"]),
                      "source_pack": str(remote / names["source_pack"]),
                      "original_priority": candidate["priority"],
                      "original_categories": sorted({issue["category"] for issue in
                          candidate["source_issues"] + candidate["audio_issues"]})})
    result = {"schema_version": "dev-pb2.shortlist.v1", "cases": cases}
    (output / "batch.json").write_text(json.dumps(result, ensure_ascii=False,
                                                  indent=2) + "\n")
    return {"cases": len(cases),
            "literal_videos": sum("audio_literal_formula" in case["original_categories"]
                                  for case in cases),
            "with_unburned": sum((output / "cases" / case["request"]["item_id"] /
                                  "unburned.mp4").is_file() for case in cases)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an isolated real-video shortlist")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.dataset, args.output, args.destination_root),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
