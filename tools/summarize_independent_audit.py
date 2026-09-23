"""Aggregate frozen candidate, second-ASR, and revised screening evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev_pb2.literal_reading import BRACKETS, FUNCTION


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _bracket_videos(clips: Path, transcripts: Path) -> tuple[int, list[str]]:
    rows = _load(clips)["items"]
    videos = set()
    for row in rows:
        target = transcripts / f"{row['item_id']}-{row['cue_index']}.json"
        result = _load(target)
        if (result.get("status") == "completed" and FUNCTION.search(row["expected_text"])
                and BRACKETS.search(result.get("text") or "")):
            videos.add(row["item_id"])
    return len(rows), sorted(videos)


def summarize(root: Path) -> dict:
    replay = _load(root / "replay-updated.json")
    original = _load(root / "clips87/clips.json")
    original_clips, original_literal = _bracket_videos(
        root / "clips87/clips.json", root / "whisper/items")
    revised = _load(root / "clean40/revised-v02/summary.json")
    repaired_clips, repaired_literal = _bracket_videos(
        root / "clean40/clips/clips.json", root / "clean40/whisper/items")
    result = {"schema_version": "dev-pb2.independent-audit.v1",
              "old_candidates": replay["original_candidates"],
              "old_unflagged": original["videos"],
              "new_videos_from_frozen_evidence": replay["new_videos"],
              "new_source_videos": replay["new_source_videos"],
              "new_literal_videos": replay["new_literal_videos"],
              "original_clip_asr": _load(root / "whisper/summary.json"),
              "original_high_risk_clips": original_clips,
              "original_literal_audio_evidence": original_literal,
              "source_second_pass_original": _load(root / "source-challenge/summary.json"),
              "full_module_check_new_five": _load(
                  root / "original-five/full-v02-summary.json")["counts"],
              "old_repair_clean_videos": revised["videos"],
              "revised_repair_screening": revised["counts"],
              "repaired_clip_asr": _load(root / "clean40/whisper/summary.json"),
              "repaired_high_risk_clips": repaired_clips,
              "repaired_literal_audio_evidence": repaired_literal,
              "source_second_pass_repaired": _load(
                  root / "clean40/source-challenge/summary.json"),
              "note": ("新候选不等于人工确认缺陷；87条仅抽取高风险片段，"
                       "不能据此推算完整视频的真实漏检率。")}
    (root / "reliability-summary.json").write_text(json.dumps(result,
        ensure_ascii=False, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.root)
    print(json.dumps({key: result[key] for key in
                      ("old_candidates", "old_unflagged", "new_videos_from_frozen_evidence",
                       "original_high_risk_clips", "old_repair_clean_videos",
                       "revised_repair_screening", "repaired_high_risk_clips")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
