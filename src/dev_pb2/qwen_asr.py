"""Batch transcription with Qwen Audio 3.1, preserving time and failure evidence."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import http.client
import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .manifest import load_manifest

MODEL = "qwen-audio-3.1-asr-flash"


def _audio_chunk(path: str, start: int, seconds: float) -> bytes:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
               "-ss", str(start), "-i", path, "-t", str(seconds), "-vn",
               "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k",
               "-f", "mp3", "pipe:1"]
    result = subprocess.run(command, capture_output=True, timeout=120, check=True)
    if not result.stdout:
        raise RuntimeError("empty_audio_chunk")
    return result.stdout


def _duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", path],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return float(result.stdout.strip())


def _response_events(raw: bytes) -> list[dict]:
    decoded = raw.decode("utf-8")
    if decoded.lstrip().startswith("{"):
        return [json.loads(decoded)]
    events = []
    for line in decoded.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                events.append(json.loads(data))
    if not events:
        raise ValueError("qwen_response_has_no_events")
    return events


def _decode_events(events: list[dict], offset_ms: int) -> dict:
    segments: list[dict] = []
    text = ""
    previous_sentence_text = ""
    previous_word_count = 0
    usage: dict = {}
    request_ids = []
    for event in events:
        if event.get("code") or event.get("error"):
            raise RuntimeError(f"qwen_error:{event.get('code') or event.get('error')}")
        output = event.get("output") or event
        if output.get("text") is not None:
            text = str(output["text"])
        if event.get("request_id") or output.get("request_id"):
            request_ids.append(event.get("request_id") or output.get("request_id"))
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        current = output.get("sentences") or [output.get("sentence")]
        for sentence in current:
            if not isinstance(sentence, dict) or not sentence.get("sentence_end"):
                continue
            cumulative = str(sentence.get("text") or "")
            words = sentence.get("words") or []
            if cumulative.startswith(previous_sentence_text):
                delta = cumulative[len(previous_sentence_text):]
                fresh_words = words[previous_word_count:]
            else:
                # Qwen may revise polished wording; keep the final text and avoid
                # inventing a precise location for the rewritten portion.
                delta = cumulative
                fresh_words = words
                segments.clear()
            if delta:
                # The word array can be reordered after polishing. The cumulative
                # sentence end is stable; consecutive final events bound each delta.
                previous_end = (segments[-1]["end_ms"] - offset_ms if segments
                                else int(sentence.get("begin_time") or 0))
                end = sentence.get("end_time")
                candidate_start = int(fresh_words[0].get("begin_time") or 0) if fresh_words else previous_end
                start = candidate_start if previous_end <= candidate_start <= int(end or 0) else previous_end
                segments.append({
                    "start_ms": offset_ms + int(start or 0),
                    "end_ms": offset_ms + int(end or 0),
                    "text": delta,
                    "words": [{"start_ms": offset_ms + int(word.get("begin_time") or 0),
                               "end_ms": offset_ms + int(word.get("end_time") or 0),
                               "text": str(word.get("text") or "")}
                              for word in fresh_words],
                })
            previous_sentence_text = cumulative
            previous_word_count = len(words)
    if not text and segments:
        text = "".join(row["text"] for row in segments)
    return {"text": text, "segments": segments,
            "usage": usage, "request_ids": list(dict.fromkeys(request_ids))}


def _transcribe_chunk(audio: bytes, key: str, endpoint: str, offset_ms: int) -> dict:
    payload = {"model": MODEL, "input": {"messages": [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {
            "data": "data:audio/mp3;base64," + base64.b64encode(audio).decode("ascii")}}
    ]}]}, "parameters": {"format": "mp3", "sample_rate": "16000"}}
    request = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "X-DashScope-SSE": "enable"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return _decode_events(_response_events(response.read()), offset_ms)
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"qwen_http_{exc.code}:{exc.read(300).decode(errors='replace')}") from exc
        except (TimeoutError, urllib.error.URLError, http.client.IncompleteRead,
                ConnectionError):
            if attempt == 3:
                raise
        time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("qwen_retry_exhausted")


def transcribe(path: str, key: str, endpoint: str) -> dict:
    duration = _duration(path)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("invalid_audio_duration")
    chunks = []
    for start in range(0, max(1, math.ceil(duration)), 240):
        audio = _audio_chunk(path, start, min(240, duration - start))
        result = _transcribe_chunk(audio, key, endpoint, start * 1000)
        chunks.append({"offset_seconds": start, **result})
    return {"model": MODEL, "duration_seconds": duration,
            "text": "".join(chunk["text"] for chunk in chunks),
            "segments": [segment for chunk in chunks for segment in chunk["segments"]],
            "chunks": [{k: v for k, v in chunk.items() if k not in {"segments", "text"}}
                       for chunk in chunks]}


def run_batch(manifest: Path, output: Path, key: str, endpoint: str,
              workers: int = 2, limit: int | None = None) -> dict:
    rows = load_manifest(manifest)
    if limit is not None:
        rows = rows[:limit]
    output.mkdir(parents=True, exist_ok=True)
    items_dir = output / "items"
    items_dir.mkdir(exist_ok=True)

    def one(row: dict) -> dict:
        item_id = row["item_id"]
        target = items_dir / (hashlib.sha256(item_id.encode()).hexdigest()[:24] + ".json")
        if target.exists():
            previous = json.loads(target.read_text())
            if previous.get("status") == "completed":
                return previous
        try:
            result = {"item_id": item_id, "status": "completed", "video_path": row["video_path"],
                      **transcribe(row["video_path"], key, endpoint)}
            if not result["text"].strip():
                result["status"] = "empty_transcript"
        except Exception as exc:  # noqa: BLE001 - preserve per-item failure evidence.
            result = {"item_id": item_id, "status": "failed_open",
                      "error": f"{type(exc).__name__}: {exc}"[:500]}
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        temp.replace(target)
        return result

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for future in concurrent.futures.as_completed([pool.submit(one, row) for row in rows]):
            results.append(future.result())
            if len(results) % 10 == 0 or len(results) == len(rows):
                print(f"qwen_asr {len(results)}/{len(rows)} failed="
                      f"{sum(row['status'] != 'completed' for row in results)}", flush=True)
    summary = {"model": MODEL, "total": len(rows),
               "completed": sum(row["status"] == "completed" for row in results),
               "empty_transcript": sum(row["status"] == "empty_transcript" for row in results),
               "failed_open": sum(row["status"] == "failed_open" for row in results)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen Audio 3.1 evidence-only batch transcription")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default=os.environ.get("DASHSCOPE_ASR_ENDPOINT", ""))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if not args.endpoint:
        parser.error("--endpoint or DASHSCOPE_ASR_ENDPOINT is required")
    print(json.dumps(run_batch(args.manifest, args.output, os.environ["DASHSCOPE_API_KEY"],
                               args.endpoint, args.workers, args.limit), ensure_ascii=False))


if __name__ == "__main__":
    main()
