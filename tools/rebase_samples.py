"""Repair absolute local paths after transferring a synthetic sample dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TEXT_SUFFIXES = {".json", ".csv", ".md", ".srt", ".py", ".html", ".txt"}


def rebase(root: Path) -> int:
    root = root.resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    first = manifest["items"][0]
    old = str(Path(first["video_path"]).parent.parent)
    new = str(root)
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if old in content and old != new:
            path.write_text(content.replace(old, new), encoding="utf-8")
            count += 1
    updated = json.loads((root / "manifest.json").read_text())["items"]
    missing = [row["item_id"] for row in updated
               if not Path(row["video_path"]).is_file()
               or not Path(row["source_path"]).is_file()]
    if missing:
        raise RuntimeError(f"missing_media_or_source:{len(missing)}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path, nargs="+")
    args = parser.parse_args()
    for dataset in args.dataset:
        print(f"{dataset}: {rebase(dataset)} text files updated")


if __name__ == "__main__":
    main()
