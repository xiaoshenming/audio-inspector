"""Resumable, less-polished local ASR evidence for literal formula readings."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

from .batch import load_manifest
from .literal_reading import FUNCTION, SPOKEN_BRACKET
from .semantic_review import _match, voiceovers
from .subtitle_cues import cue_match_score, read_srt_cues


def target_clips(record: dict, max_clips: int = 3) -> list[dict]:
    source = Path(record["source_path"]).read_text(encoding="utf-8")
    lines = [row for row in voiceovers(source)
             if FUNCTION.search(row["text"]) and not SPOKEN_BRACKET.search(row["text"])]
    if not lines:
        return []
    subtitle_path = str(record.get("subtitle_path") or "")
    cues = read_srt_cues(Path(subtitle_path)) if subtitle_path else []
    relevant = [cue for cue in cues
                if any(_match(cue["text"], row["text"])
                       or _match(row["text"], cue["text"]) for row in lines)]
    if not relevant and cues:
        for row in lines:
            best = max(cues, key=lambda cue: cue_match_score(row["text"], cue["text"]))
            score = cue_match_score(row["text"], best["text"])
            if score >= 0.68 and best not in relevant:
                relevant.append(best)
        relevant.sort(key=lambda cue: cue["start_seconds"])
    if not relevant:
        return [{"start_seconds": 0.0, "end_seconds": 30.0}] if not cues else []
    if len(relevant) > max_clips:
        indices = {round(i * (len(relevant) - 1) / max(1, max_clips - 1))
                   for i in range(max_clips)}
        relevant = [relevant[i] for i in sorted(indices)]
    return [{"start_seconds": max(0.0, cue["start_seconds"] - 1.0),
             "end_seconds": cue["end_seconds"] + 1.0} for cue in relevant]


def _transcribe_targeted(model, record: dict, clips: list[dict]) -> list[dict]:
    spans = []
    with tempfile.TemporaryDirectory() as temporary:
        wav = Path(temporary) / "speech.wav"
        for clip in clips:
            start = clip["start_seconds"]
            duration = clip["end_seconds"] - start
            subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-ss", str(start), "-i", record["video_path"], "-t", str(duration),
                 "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                 "-y", str(wav)],
                capture_output=True, timeout=60, check=True,
            )
            segments, _ = model.transcribe(str(wav), language="zh", vad_filter=False,
                                            condition_on_previous_text=False)
            for segment in segments:
                spans.append({"start_ms": round((start + float(segment.start)) * 1000),
                              "end_ms": round((start + float(segment.end)) * 1000),
                              "text": str(segment.text).strip()})
    return spans


def run_batch(manifest: Path, output: Path, model_name: str = "small",
              cpu_threads: int = 4, limit: int | None = None,
              targeted: bool = False, max_clips: int = 3) -> dict:
    from faster_whisper import WhisperModel

    rows = load_manifest(manifest)
    if limit is not None:
        rows = rows[:limit]
    items = output / "items"
    items.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         cpu_threads=cpu_threads)
    results = []
    started = time.monotonic()
    for row in rows:
        item_id = row["item_id"]
        target = items / (hashlib.sha256(item_id.encode()).hexdigest()[:24] + ".json")
        clips = target_clips(row, max_clips) if targeted else []
        if target.is_file():
            previous = json.loads(target.read_text())
            if (previous.get("status") == "completed"
                    and previous.get("targeted") == targeted
                    and previous.get("clips") == clips):
                results.append(previous)
                continue
        try:
            if targeted:
                spans = _transcribe_targeted(model, row, clips) if clips else []
                duration = sum(clip["end_seconds"] - clip["start_seconds"] for clip in clips)
            else:
                segments, info = model.transcribe(row["video_path"], language="zh",
                                                  vad_filter=False)
                spans = [{"start_ms": round(float(segment.start) * 1000),
                          "end_ms": round(float(segment.end) * 1000),
                          "text": str(segment.text).strip()} for segment in segments]
                duration = float(info.duration)
            result = {"item_id": item_id, "status": "completed",
                      "model": f"faster-whisper-{model_name}",
                      "duration_seconds": duration, "targeted": targeted,
                      "clips": clips,
                      "text": "".join(span["text"] for span in spans), "segments": spans}
            if clips and not result["text"].strip():
                result["status"] = "empty_transcript"
        except Exception as exc:  # noqa: BLE001 - retain per-item failure evidence.
            result = {"item_id": item_id, "status": "failed_open",
                      "error": f"{type(exc).__name__}: {exc}"[:500]}
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        temp.replace(target)
        results.append(result)
        if len(results) % 10 == 0 or len(results) == len(rows):
            print(f"literal_asr {len(results)}/{len(rows)} failed="
                  f"{sum(x['status'] != 'completed' for x in results)}"
                  f" elapsed={round(time.monotonic() - started)}s", flush=True)
    summary = {"model": model_name, "total": len(rows),
               "completed": sum(x["status"] == "completed" for x in results),
               "empty_transcript": sum(x["status"] == "empty_transcript" for x in results),
               "failed_open": sum(x["status"] == "failed_open" for x in results),
               "scoped_videos": sum(bool(x.get("clips")) for x in results),
               "clips_transcribed": sum(len(x.get("clips") or []) for x in results),
               "elapsed_seconds": round(time.monotonic() - started, 1)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Local literal speech recognition")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="small")
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--targeted", action="store_true")
    parser.add_argument("--max-clips", type=int, default=3)
    args = parser.parse_args()
    if args.cpu_threads < 1 or args.max_clips < 1:
        parser.error("--cpu-threads and --max-clips must be positive")
    print(json.dumps(run_batch(args.manifest, args.output, args.model,
                               args.cpu_threads, args.limit, args.targeted,
                               args.max_clips), ensure_ascii=False))


if __name__ == "__main__":
    main()
