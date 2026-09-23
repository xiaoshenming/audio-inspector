"""Extract math-heavy clips across each previously unflagged real video."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from dev_pb2.subtitle_cues import read_srt_cues

RISK = re.compile(r"[A-Za-zα-ωΑ-Ω0-9]|加|减|负|平方|立方|函数|向量|分母|分子|根号|集合|选项")


def choose(cues: list[dict]) -> list[tuple[int, dict]]:
    if not cues:
        return []
    groups = [[], [], []]
    total = cues[-1]["end_seconds"]
    for index, cue in enumerate(cues):
        third = min(2, int(3 * cue["start_seconds"] / max(total, 0.001)))
        groups[third].append((index, cue))
    selected = []
    for group in groups:
        if not group:
            continue
        selected.append(max(group, key=lambda pair: (
            len(RISK.findall(pair[1]["text"])), len(pair[1]["text"]))))
    return selected


def _duration(video: str) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration", "-of", "default=nw=1:nk=1", video],
                            capture_output=True, text=True, timeout=30, check=True)
    return float(result.stdout.strip())


def prepare(manifest: Path, output: Path) -> dict:
    rows = json.loads(manifest.read_text())["items"]
    clips = output / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    result = []
    missing_subtitle = []
    for index, row in enumerate(rows, 1):
        subtitle = Path(row.get("subtitle_path") or "")
        cues = read_srt_cues(subtitle) if subtitle.is_file() else []
        if not cues:
            missing_subtitle.append(row["item_id"])
            duration = _duration(row["video_path"])
            for fallback_index, start in enumerate((0.0, max(0.0, duration / 2 - 5),
                                                    max(0.0, duration - 10)), 1):
                target = clips / f"{row['item_id']}-fallback-{fallback_index}.mp3"
                if not target.is_file():
                    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel",
                                    "error", "-ss", f"{start:.3f}", "-i", row["video_path"],
                                    "-t", "10", "-vn", "-ac", "1", "-ar", "16000",
                                    "-c:a", "libmp3lame", "-b:a", "48k", "-y",
                                    str(target)], capture_output=True, timeout=90, check=True)
                result.append({"item_id": row["item_id"],
                               "cue_index": -fallback_index, "expected_text": "",
                               "start_seconds": start, "end_seconds": start + 10,
                               "clip": str(target.relative_to(output))})
            continue
        for cue_index, cue in choose(cues):
            start = max(0.0, cue["start_seconds"] - 0.5)
            duration = cue["end_seconds"] - start + 0.5
            target = clips / f"{row['item_id']}-{cue_index + 1}.mp3"
            if not target.is_file() or target.stat().st_size < 1000:
                subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel",
                                "error", "-ss", f"{start:.3f}", "-i", row["video_path"],
                                "-t", f"{duration:.3f}", "-vn", "-ac", "1",
                                "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k",
                                "-y", str(target)], capture_output=True, timeout=90,
                               check=True)
            result.append({"item_id": row["item_id"], "cue_index": cue_index + 1,
                           "expected_text": cue["text"], "start_seconds": start,
                           "end_seconds": start + duration,
                           "clip": str(target.relative_to(output))})
        if index % 10 == 0:
            print(f"prepared {index}/{len(rows)}", flush=True)
    payload = {"items": result, "missing_subtitle": missing_subtitle,
               "videos": len(rows), "clips": len(result)}
    (output / "clips.json").write_text(json.dumps(payload, ensure_ascii=False,
                                                  indent=2) + "\n")
    return {"videos": len(rows), "clips": len(result),
            "missing_subtitle": len(missing_subtitle)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.manifest, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
