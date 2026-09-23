"""Small, explicit manifest contract for the independent screening module."""

from __future__ import annotations

import json
from pathlib import Path


def load_manifest(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise TypeError("manifest must contain an items list")
    result: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise TypeError(f"manifest item {index} is not an object")
        item_id = str(raw.get("item_id") or "").strip()
        if not item_id or item_id in seen:
            raise ValueError(f"missing or duplicate item_id at item {index}")
        video = Path(str(raw.get("video_path") or "")).expanduser().resolve()
        source = Path(str(raw.get("source_path") or "")).expanduser().resolve()
        if not video.is_file() or not source.is_file():
            raise ValueError(f"missing video or source for {item_id}")
        seen.add(item_id)
        result.append({**raw, "item_id": item_id, "video_path": str(video),
                       "source_path": str(source)})
    return result
