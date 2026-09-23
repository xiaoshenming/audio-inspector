"""Find audible punctuation names next to raw function notation in final voiceovers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .batch import load_manifest
from .semantic_review import _match, voiceovers
from .subtitle_cues import cue_match_score, read_srt_cues

FUNCTION = re.compile(r"(?<![A-Za-z0-9_])(?:[fgh]|sin|cos|tan|ln)'?\s*\([^()]{1,20}\)",
                      re.IGNORECASE)
BRACKETS = re.compile(
    r"左[小中大]?[括扣扩拓阔口][号弧].{0,45}?右[小中大]?[括扣扩拓阔口][号弧]"
)
SPOKEN_BRACKET = re.compile(r"[左右][小中大]?[括扣扩拓阔口][号弧]")


def _excerpt(text: str, match: re.Match) -> str:
    return text[max(0, match.start() - 18): min(len(text), match.end() + 18)].strip()


def detect_one(record: dict, asr: dict) -> list[dict]:
    if asr.get("status") != "completed":
        raise ValueError("literal_asr_unavailable")
    lines = [row for row in voiceovers(Path(record["source_path"]).read_text(encoding="utf-8"))
             if FUNCTION.search(row["text"]) and not SPOKEN_BRACKET.search(row["text"])]
    if not lines:
        return []
    subtitle = str(record.get("subtitle_path") or "")
    cues = read_srt_cues(Path(subtitle)) if subtitle else []
    issues = []
    seen = set()
    for segment in asr.get("segments") or []:
        spoken = str(segment.get("text") or "")
        pairs = list(BRACKETS.finditer(spoken))
        if not pairs:
            continue
        start_ms = int(segment["start_ms"])
        end_ms = int(segment["end_ms"])
        aligned = [cue for cue in cues
                   if cue["start_seconds"] * 1000 <= end_ms + 2000
                   and cue["start_seconds"] * 1000 >= start_ms - 3000]
        source = next((row for cue in aligned for row in lines
                       if _match(cue["text"], row["text"])
                       or _match(row["text"], cue["text"])
                       or cue_match_score(row["text"], cue["text"]) >= 0.68), None)
        if source is None and not cues:
            source = lines[0]
        if source is None:
            continue
        formula = FUNCTION.search(source["text"])
        for pair in pairs:
            identity = (source["line"], start_ms)
            if identity in seen:
                continue
            seen.add(identity)
            issues.append({
                "kind": "audio", "category": "audio_literal_formula",
                "confidence": "high" if cues else "medium",
                "line": source["line"],
                "source_quote": source["text"][:500],
                "asr_quote": _excerpt(spoken, pair),
                "formula": formula.group(),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "time_seconds": round(start_ms / 1000, 2),
                "why": ("最终旁白写的是公式记号，但第二路逐字识别听到“左括号…右括号”"
                        "一类机械念法；Qwen 转写可能把它整理回公式。请以视频实际发音核听。"),
            })
    return issues


def run_batch(manifest: Path, asr_dir: Path, output: Path) -> dict:
    records = load_manifest(manifest)
    asr_items = {}
    for path in (asr_dir / "items").glob("*.json"):
        result = json.loads(path.read_text(encoding="utf-8"))
        asr_items[result["item_id"]] = result
    items_dir = output / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for record in records:
        item_id = record["item_id"]
        try:
            issues = detect_one(record, asr_items.get(item_id) or {})
            result = {"item_id": item_id, "status": "completed", "issues": issues}
        except Exception as exc:  # noqa: BLE001 - preserve per-item evidence status.
            result = {"item_id": item_id, "status": "failed_open",
                      "error": f"{type(exc).__name__}: {exc}"[:500]}
        (items_dir / f"{item_id}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(result)
    summary = {"total": len(results),
               "completed": sum(row["status"] == "completed" for row in results),
               "failed_open": sum(row["status"] != "completed" for row in results),
               "candidate_videos": sum(bool(row.get("issues")) for row in results),
               "issue_count": sum(len(row.get("issues") or []) for row in results)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen for literal function punctuation readings")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--asr-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_batch(args.manifest, args.asr_dir, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
