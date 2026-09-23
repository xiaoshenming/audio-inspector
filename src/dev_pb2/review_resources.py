"""Bind every review input to immutable bytes, including the source archive."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def source_pack_main_digest(archive: Path) -> str:
    with tarfile.open(archive, "r:*") as source:
        matches = [member for member in source.getmembers()
                   if member.name == "main.py" and member.isfile()]
        if len(matches) != 1:
            raise ValueError("source_pack_requires_one_main_py")
        stream = source.extractfile(matches[0])
        if stream is None:
            raise ValueError("source_pack_main_unreadable")
        value = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
        return value.hexdigest()


def paths(state: dict) -> dict[str, str]:
    request = state["request"]
    return {"video": request["video_path"], "source": request["source_path"],
            "subtitle": request.get("subtitle_path") or "",
            "unburned": state.get("unburned_path") or "",
            "source_pack": state.get("source_pack_path") or ""}


def snapshot(state: dict, *, check_pack: bool = True) -> dict[str, str]:
    result = {}
    for name, raw in paths(state).items():
        if not raw:
            result[name] = ""
            continue
        path = Path(raw)
        if not path.is_file():
            raise ValueError(f"{name}_file_missing")
        result[name] = digest(path)
    archive = state.get("source_pack_path")
    if check_pack and archive and source_pack_main_digest(Path(archive)) != result["source"]:
        raise ValueError("source_pack_main_mismatch")
    return result


def verify(state: dict) -> None:
    current = snapshot(state, check_pack=False)
    for name, expected in state["resource_sha256"].items():
        if current[name] != expected:
            raise ValueError(f"stale_{name}_revision")
    inspection = state["inspection"]
    for name in ("video", "source"):
        if current[name] != inspection[f"{name}_sha256"]:
            raise ValueError(f"stale_{name}_revision")
    archive = state.get("source_pack_path")
    if archive and source_pack_main_digest(Path(archive)) != current["source"]:
        raise ValueError("source_pack_main_mismatch")
