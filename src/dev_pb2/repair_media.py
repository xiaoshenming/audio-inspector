"""Deterministic, subtitle-aligned revoice of an approved final video."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from .review_resources import source_pack_main_digest
from .source_revision import revise_pack
from .subtitle_cues import read_srt_cues
from .synthetic_tts import _digest, _download_audio, _duration, _post_tts, _stamp

SUBTITLE_STYLE = (
    "FontName=Noto Sans CJK SC,FontSize=14,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00101010,BackColour=&H00000000,BorderStyle=1,"
    "Outline=0.65,Shadow=0.85,Alignment=2,MarginL=18,MarginR=18,MarginV=14"
)


@lru_cache(maxsize=1)
def supports_burned_subtitles() -> bool:
    result = subprocess.run(["ffmpeg", "-filters"], capture_output=True, text=True,
                            timeout=10, check=False)
    return result.returncode == 0 and bool(re.search(
        r"(?m)^\s*\S+\s+subtitles\s+V->V\b", result.stdout))


def validate_tts_profile(value: dict | None) -> dict:
    if not isinstance(value, dict):
        raise TypeError("tts_profile_required")
    if (value.get("provider") != "qwen_audio"
            or not isinstance(value.get("model"), str)
            or not value["model"].startswith("qwen-audio-")
            or not isinstance(value.get("voice"), str)
            or not value["voice"].strip()
            or not isinstance(value.get("speech_rate"), (int, float))
            or not 0.5 <= value["speech_rate"] <= 2.0):
        raise ValueError("unsupported_local_tts_profile")
    return {"provider": value["provider"], "model": value["model"],
            "voice": value["voice"], "speech_rate": value["speech_rate"]}


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            timeout=900, check=False)
    if result.returncode:
        raise RuntimeError("media_command_failed:" + result.stderr[-1200:])


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _write_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".repair-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _changed_cues(subtitle: Path, overrides: list[dict]) -> tuple[list[dict], list[dict]]:
    cues = read_srt_cues(subtitle)
    selected = []
    for override in overrides:
        old = override["old_voiceover"].strip()
        matches = [index for index, cue in enumerate(cues) if cue["text"].strip() == old]
        if len(matches) != 1:
            raise ValueError("approved_voiceover_has_no_unique_subtitle_cue")
        index = matches[0]
        cues[index] = {**cues[index], "text": override["new_voiceover"].strip()}
        selected.append({**cues[index], "old_text": old, "index": index})
    if len({cue["index"] for cue in selected}) != len(selected):
        raise ValueError("multiple_overrides_in_one_subtitle_cue")
    return cues, sorted(selected, key=lambda cue: cue["start_seconds"])


def _write_srt(cues: list[dict], path: Path) -> None:
    blocks = [f"{index}\n{_stamp(cue['start_seconds'])} --> "
              f"{_stamp(cue['end_seconds'])}\n{cue['text']}\n"
              for index, cue in enumerate(cues, 1)]
    path.write_text("\n".join(blocks) + "\n", encoding="utf-8")


def _audio_filter(changes: list[dict], total: float) -> tuple[str, str]:
    parts = []
    labels = []
    previous = 0.0
    for index, change in enumerate(changes, 1):
        start, end = change["start_seconds"], change["end_seconds"]
        if start < previous or end <= start or end > total + 0.2:
            raise ValueError("invalid_or_overlapping_subtitle_timeline")
        if start - previous > 0.001:
            label = f"a{len(labels)}"
            parts.append(f"[0:a]atrim=start={previous:.3f}:end={start:.3f},"
                         f"asetpts=PTS-STARTPTS,apad,"
                         f"atrim=duration={start - previous:.3f}[{label}]")
            labels.append(label)
        label = f"a{len(labels)}"
        parts.append(f"[{index}:a]atempo={change['tempo']:.6f},apad,"
                     f"atrim=duration={end - start:.3f},asetpts=PTS-STARTPTS[{label}]")
        labels.append(label)
        previous = end
    if total - previous > 0.001:
        label = f"a{len(labels)}"
        parts.append(f"[0:a]atrim=start={previous:.3f}:end={total:.3f},"
                     f"asetpts=PTS-STARTPTS,apad,"
                     f"atrim=duration={total - previous:.3f}[{label}]")
        labels.append(label)
    parts.append("".join(f"[{label}]" for label in labels)
                 + f"concat=n={len(labels)}:v=0:a=1[aout]")
    return ";".join(parts), "[aout]"


def rebuild(inspection: dict, decision: dict, *, video: Path, unburned: Path,
            subtitle: Path, source_pack: Path, output: Path,
            api_key: str, tts_endpoint: str,
            tts_profile: dict | None = None) -> dict:
    if decision.get("action") != "approve_repair" or not decision.get("voiceover_overrides"):
        raise ValueError("approved_repair_required")
    if (decision["item_id"] != inspection["item_id"]
            or decision["revision_id"] != inspection["revision_id"]
            or decision["video_sha256"] != _digest(video)
            or decision["source_sha256"] != inspection["source_sha256"]):
        raise ValueError("stale_repair_identity")
    subtitle_sha = inspection.get("subtitle_sha256") or ""
    if (decision.get("subtitle_sha256", "") != subtitle_sha
            or (subtitle_sha and (not subtitle.is_file() or _digest(subtitle) != subtitle_sha))):
        raise ValueError("stale_subtitle_revision")
    if source_pack_main_digest(source_pack) != inspection["source_sha256"]:
        raise ValueError("source_pack_main_mismatch")
    profile = validate_tts_profile(tts_profile)
    if not supports_burned_subtitles():
        raise RuntimeError("ffmpeg_subtitles_filter_required")
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "repair-receipt.json"
    previous = _read_json(receipt)
    if (previous and previous.get("idempotency_key") == decision["idempotency_key"]
            and previous.get("tts_profile") == profile
            and (output / "final.mp4").is_file()
            and _digest(output / "final.mp4") == previous.get("video_sha256")):
        return previous
    profile_path = output / "tts-profile.json"
    previous_profile = _read_json(profile_path)
    _write_json(profile_path, profile)
    earlier_cues = read_srt_cues(output / "corrected.srt")
    main = revise_pack(source_pack, decision["voiceover_overrides"], output)
    cues, changes = _changed_cues(subtitle, decision["voiceover_overrides"])
    _write_srt(cues, output / "corrected.srt")
    tts_evidence = []
    for index, change in enumerate(changes, 1):
        audio = output / f"replacement-{index}.mp3"
        evidence_path = output / f"replacement-{index}.json"
        text_sha = hashlib.sha256(change["text"].encode()).hexdigest()
        previous = _read_json(evidence_path)
        if (previous.get("text_sha256") == text_sha
                and previous.get("tts_profile") == profile and audio.is_file()
                and _digest(audio) == previous.get("audio_sha256")):
            response = {"request_id": previous["request_id"],
                        "characters_billed": previous["characters_billed"]}
        elif (previous == {} and previous_profile == profile and audio.is_file()
              and audio.stat().st_size > 1000
              and change["index"] < len(earlier_cues)
              and earlier_cues[change["index"]]["text"] == change["text"]):
            response = {"request_id": "recovered_incomplete_attempt",
                        "characters_billed": None}
            _write_json(evidence_path, {**response, "tts_profile": profile,
                                        "text_sha256": text_sha,
                                        "audio_sha256": _digest(audio)})
        else:
            response = _post_tts({"tts_model": profile["model"],
                                  "tts_text": change["text"],
                                  "voice": profile["voice"],
                                  "rate": profile["speech_rate"], "seed": index},
                                 api_key, tts_endpoint)
            _download_audio(response.pop("audio_url"), audio)
            _write_json(evidence_path, {**response, "tts_profile": profile,
                                        "text_sha256": text_sha,
                                        "audio_sha256": _digest(audio)})
        duration = _duration(audio)
        cue_duration = change["end_seconds"] - change["start_seconds"]
        tempo = duration / cue_duration
        if not 0.6 <= tempo <= 1.4:
            raise ValueError("replacement_duration_requires_scene_rerender")
        change["tempo"] = tempo
        tts_evidence.append({"request_id": response["request_id"],
                             "characters_billed": response["characters_billed"],
                             "cue_index": change["index"] + 1,
                             "generated_seconds": round(duration, 3),
                             "target_seconds": round(cue_duration, 3),
                             "tempo": round(tempo, 3),
                             "audio_sha256": _digest(audio)})
    if not unburned.is_file():
        raise ValueError("unburned_video_required_for_corrected_subtitles")
    total = _duration(unburned)
    graph, audio_label = _audio_filter(changes, total)
    inputs = [arg for index in range(1, len(changes) + 1)
              for arg in ("-i", f"replacement-{index}.mp3")]
    _run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
          "-i", str(unburned), *inputs, "-filter_complex", graph,
          "-map", "0:v:0", "-map", audio_label, "-c:v", "copy",
          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
          "-t", f"{total:.3f}", "corrected-unburned.mp4"], cwd=output)
    _run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
          "-i", "corrected-unburned.mp4", "-vf",
          f"subtitles=filename=corrected.srt:force_style='{SUBTITLE_STYLE}'",
          "-c:v", "libx264", "-preset", "fast", "-crf", "18",
          "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
          "final.mp4"], cwd=output)
    final = output / "final.mp4"
    if abs(_duration(final) - total) > 0.15:
        raise RuntimeError("repaired_video_duration_drift")
    result = {"schema_version": "dev-pb2.repair.v1", "status": "completed",
              "item_id": inspection["item_id"], "parent_revision_id": inspection["revision_id"],
              "idempotency_key": decision["idempotency_key"],
              "video_path": str(final), "video_sha256": _digest(final),
              "source_path": str(main), "source_sha256": _digest(main),
              "source_pack_path": str(output / "source.tar"),
              "subtitle_path": str(output / "corrected.srt"),
              "subtitle_sha256": _digest(output / "corrected.srt"),
              "tts": tts_evidence, "tts_profile": profile,
              "duration_seconds": _duration(final)}
    _write_json(receipt, result)
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Revoice and rebuild an approved final MP4")
    for name in ("inspection", "decision", "video", "unburned", "subtitle",
                 "source-pack", "output", "tts-profile"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = rebuild(json.loads(args.inspection.read_text()),
                     json.loads(args.decision.read_text()),
                     video=args.video, unburned=args.unburned, subtitle=args.subtitle,
                     source_pack=args.source_pack, output=args.output,
                     api_key=os.environ["DASHSCOPE_API_KEY"],
                     tts_endpoint=os.environ["DASHSCOPE_TTS_ENDPOINT"],
                     tts_profile=json.loads(args.tts_profile.read_text()))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
