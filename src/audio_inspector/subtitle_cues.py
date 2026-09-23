"""Read the final subtitle timeline without changing its spoken text."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path


def cue_match_score(left: str, right: str) -> float:
    def compact(value: str) -> str:
        return re.sub(r"\s+", "", re.sub(r"\\([A-Za-z]+)", r"\1", value).replace("$", ""))

    return SequenceMatcher(None, compact(left), compact(right)).ratio()


def read_srt_cues(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    cues = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig")):
        match = re.search(
            r"(\d\d):(\d\d):(\d\d),(\d\d\d)\s*-->\s*"
            r"(\d\d):(\d\d):(\d\d),(\d\d\d)\s*\n([\s\S]*)", block)
        if not match:
            continue
        h, m, s, ms = map(int, match.groups()[:4])
        eh, em, es, ems = map(int, match.groups()[4:8])
        cues.append({"start_seconds": h * 3600 + m * 60 + s + ms / 1000,
                     "end_seconds": eh * 3600 + em * 60 + es + ems / 1000,
                     "text": match.group(9).strip().replace("\n", " ")})
    return cues
