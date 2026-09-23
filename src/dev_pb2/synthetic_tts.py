"""Resumable synthetic TTS calls, downloaded audio, and matching MP4 manifests."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _post_tts(case: dict, key: str, endpoint: str) -> dict:
    payload = {"model": case["tts_model"], "input": {
        "text": case["tts_text"], "voice": case["voice"],
        "format": "mp3", "sample_rate": 24000, "rate": case["rate"],
        "seed": case["seed"],
    }}
    request = urllib.request.Request(
        endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST", headers={"Authorization": "Bearer " + key,
                                "Content-Type": "application/json"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
            output = result.get("output") or {}
            audio = output.get("audio") or {}
            if output.get("finish_reason") != "stop" or not audio.get("url"):
                raise RuntimeError("tts_incomplete_response")
            return {"request_id": result.get("request_id"),
                    "characters_billed": (result.get("usage") or {}).get("characters"),
                    "audio_url": audio["url"]}
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"tts_http_{exc.code}:{exc.read(240).decode(errors='replace')}") from exc
        except (TimeoutError, urllib.error.URLError):
            if attempt == 3:
                raise
        time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("tts_retry_exhausted")


def _download_audio(url: str, target: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not (parsed.hostname or "").endswith(".aliyuncs.com"):
        raise ValueError("unexpected_tts_audio_host")
    temp = target.with_suffix(".tmp.mp3")
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temp.open("wb") as sink:
            while chunk := response.read(1024 * 1024):
                sink.write(chunk)
        if temp.stat().st_size < 1000:
            raise RuntimeError("tts_audio_too_small")
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return float(result.stdout.strip())


def _video(audio: Path, target: Path) -> None:
    temporary = target.with_suffix(".tmp.mp4")
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=0x17233b:s=640x360:r=1",
             "-i", str(audio), "-c:v", "libx264", "-preset", "ultrafast",
             "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-y", str(temporary)],
            capture_output=True, timeout=120, check=True,
        )
        if _duration(temporary) <= 0:
            raise RuntimeError("synthetic_video_empty")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _stamp(seconds: float) -> str:
    value = max(0, round(seconds * 1000))
    hours, rem = divmod(value, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _subtitles(text: str, duration: float) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[。！？；])", text) if part.strip()]
    weight = sum(len(part) for part in parts)
    elapsed = 0.0
    blocks = []
    for index, part in enumerate(parts, 1):
        end = duration if index == len(parts) else elapsed + duration * len(part) / weight
        blocks.append(f"{index}\n{_stamp(elapsed)} --> {_stamp(end)}\n{part}\n")
        elapsed = end
    return "\n".join(blocks) + "\n"


def synthesize_one(case: dict, root: Path, key: str, endpoint: str) -> dict:
    item_id = case["item_id"]
    result_path = root / "metadata" / "tts-results" / f"{item_id}.json"
    audio = root / "audio" / f"{item_id}.mp3"
    video = root / "videos" / f"{item_id}.mp4"
    subtitle = root / "subtitles" / f"{item_id}.srt"
    if result_path.is_file():
        previous = json.loads(result_path.read_text())
        if (previous.get("status") == "completed" and audio.is_file() and video.is_file()
                and _digest(audio) == previous.get("audio_sha256")
                and _digest(video) == previous.get("video_sha256")):
            return previous
    started = time.monotonic()
    try:
        response = _post_tts(case, key, endpoint)
        _download_audio(response.pop("audio_url"), audio)
        _video(audio, video)
        duration = _duration(video)
        subtitle.write_text(_subtitles(case["source_text"], duration), encoding="utf-8")
        result = {"item_id": item_id, "status": "completed",
                  "model": case["tts_model"], "voice": case["voice"],
                  "duration_seconds": duration, "audio_sha256": _digest(audio),
                  "video_sha256": _digest(video),
                  "elapsed_seconds": round(time.monotonic() - started, 2), **response}
    except Exception as exc:  # noqa: BLE001 - one failed case must stay visible.
        result = {"item_id": item_id, "status": "failed_open",
                  "error": f"{type(exc).__name__}: {exc}"[:500],
                  "elapsed_seconds": round(time.monotonic() - started, 2)}
    temp = result_path.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temp.replace(result_path)
    return result


def run_batch(root: Path, key: str, endpoint: str, workers: int = 4,
              limit: int | None = None, split: str | None = None) -> dict:
    all_cases = json.loads((root / "metadata" / "oracle.json").read_text())
    cases = [case for case in all_cases if split is None or case["split"] == split]
    if limit is not None:
        cases = cases[:limit]
    for name in ("metadata/tts-results", "audio", "videos", "subtitles"):
        (root / name).mkdir(parents=True, exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(synthesize_one, case, root, key, endpoint) for case in cases]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            if len(results) % 10 == 0 or len(results) == len(cases):
                print(f"synthetic_tts {len(results)}/{len(cases)} failed="
                      f"{sum(x['status'] != 'completed' for x in results)}", flush=True)
    successful = {row["item_id"] for row in results if row["status"] == "completed"}
    all_rows = {result["item_id"]: result
                for path in (root / "metadata/tts-results").glob("*.json")
                if (result := json.loads(path.read_text())).get("status") == "completed"}
    all_successful = set(all_rows)
    manifest = {"items": [{"item_id": case["item_id"],
                           "video_path": str((root / "videos" / f"{case['item_id']}.mp4").resolve()),
                           "source_path": str((root / "sources" / f"{case['item_id']}.py").resolve()),
                           "subtitle_path": str((root / "subtitles" / f"{case['item_id']}.srt").resolve())}
                          for case in all_cases if case["item_id"] in all_successful]}
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with (root / "metadata/samples.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["item_id", "external_key", "batch_name",
                                                     "tts_status", "duration_seconds",
                                                     "subtitle_path", "voice_id"])
        writer.writeheader()
        for number, case in enumerate(all_cases, 1):
            if case["item_id"] not in all_successful:
                continue
            writer.writerow({"item_id": case["item_id"], "external_key": f"SYN-{number:04d}",
                             "batch_name": case["group"], "tts_status": "completed",
                             "duration_seconds": all_rows[case["item_id"]]["duration_seconds"],
                             "subtitle_path": str((root / "subtitles" / f"{case['item_id']}.srt").resolve()),
                             "voice_id": case["voice"]})
    summary = {"total": len(cases), "completed": len(successful),
               "failed_open": len(cases) - len(successful),
               "all_completed": len(all_successful),
               "split": split or "all",
               "billed_characters": sum(row.get("characters_billed") or 0 for row in results),
               "duration_hours": round(sum(row.get("duration_seconds") or 0 for row in results) / 3600, 2)}
    (root / "metadata" / "tts-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize deterministic synthetic TTS cases")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--endpoint", default=os.environ.get("DASHSCOPE_TTS_ENDPOINT", ""))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--split", choices=("calibration", "holdout"))
    args = parser.parse_args()
    if not args.endpoint or args.workers < 1:
        parser.error("DASHSCOPE_TTS_ENDPOINT/--endpoint and positive workers required")
    print(json.dumps(run_batch(args.root, os.environ["DASHSCOPE_API_KEY"],
                               args.endpoint, args.workers, args.limit,
                               args.split), ensure_ascii=False))


if __name__ == "__main__":
    main()
