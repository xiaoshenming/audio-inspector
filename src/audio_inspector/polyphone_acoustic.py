"""多音字声学首筛与疑似项三窗复核。"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from .phonetic_ctc import (
    PhoneticClip,
    PhoneticCtc,
    compare_windows,
    expected_zhuyin,
)
from .polyphone_batch_inputs import Candidate


def score_video(
    video: Path,
    candidates: list[Candidate],
    engine: PhoneticCtc,
    *,
    batch_size: int,
) -> list[dict]:
    if not candidates:
        return []
    samples = _extract_samples(video)
    observed = _transcribe_unique(
        samples, candidates, range(len(candidates)), (0.35,),
        engine, batch_size,
    )
    metadata = [_metadata(candidate) for candidate in candidates]
    _isolate_occurrences(candidates, metadata, observed, ("main",))
    suspects = [
        index for index, item in enumerate(metadata)
        if _contains_alternative(observed.get(f"{index}:main", ""), item)
    ]
    suspect_set = set(suspects)
    suspect_spans = {
        (candidates[index].start, candidates[index].end)
        for index in suspects
    }
    extra_indices = [
        index for index, candidate in enumerate(candidates)
        if (candidate.start, candidate.end) in suspect_spans
    ]
    observed.update(_transcribe_unique(
        samples, candidates, extra_indices, (0.15, 0.65),
        engine, batch_size,
    ))
    _isolate_occurrences(candidates, metadata, observed, ("0.15", "0.65"))
    return [
        _finding(index, candidate, metadata[index], observed, index in suspect_set)
        for index, candidate in enumerate(candidates)
    ]


def _finding(
    index: int,
    candidate: Candidate,
    metadata: dict,
    observed: dict,
    suspect: bool,
) -> dict:
    main = observed.get(f"{index}:main", "")
    if suspect:
        windows = [
            main,
            observed.get(f"{index}:0.15", ""),
            observed.get(f"{index}:0.65", ""),
        ]
        status, alternative = compare_windows(
            metadata["expected"], windows, metadata["alternatives"],
        )
    else:
        windows = [main]
        status = "passed" if metadata["expected"] and metadata["expected"] in _plain(main) else "uncertain"
        alternative = None
    payload = asdict(candidate)
    payload.update({
        "status": status,
        "expected_zhuyin": metadata["expected"],
        "alternative_zhuyin": metadata["alternatives"],
        "observed_windows": windows,
        "observed_alternative": alternative,
    })
    return payload


def _metadata(candidate: Candidate) -> dict:
    expected = expected_zhuyin(candidate.char, [candidate.expected_pinyin])
    alternatives = [
        value for value in (
            expected_zhuyin(candidate.char, [pinyin])
            for pinyin in candidate.alternative_pinyin
        )
        if value
    ]
    return {
        "expected": expected,
        "alternatives": alternatives,
    }


def _contains_alternative(value: str, metadata: dict) -> bool:
    plain = _plain(value)
    return any(alternative in plain for alternative in metadata["alternatives"])


def _transcribe_unique(
    samples,
    candidates: list[Candidate],
    indices,
    paddings: tuple[float, ...],
    engine: PhoneticCtc,
    batch_size: int,
) -> dict[str, str]:
    unique: dict[tuple[float, float, float], str] = {}
    aliases: dict[str, str] = {}
    clips = []
    for index in indices:
        candidate = candidates[index]
        for padding in paddings:
            label = "main" if padding == 0.35 else str(padding)
            key = (candidate.start, candidate.end, padding)
            clip_id = unique.get(key)
            if clip_id is None:
                clip_id = f"span:{len(unique)}"
                unique[key] = clip_id
                clips.append(PhoneticClip(
                    clip_id, _slice(samples, candidate, padding),
                ))
            aliases[f"{index}:{label}"] = clip_id
    decoded = engine.transcribe(clips, batch_size=batch_size) if clips else {}
    return {alias: decoded.get(clip_id, "") for alias, clip_id in aliases.items()}


def _isolate_occurrences(
    candidates: list[Candidate],
    metadata: list[dict],
    observed: dict[str, str],
    labels: tuple[str, ...],
) -> None:
    groups: dict[tuple[float, float, str], list[int]] = {}
    for index, candidate in enumerate(candidates):
        groups.setdefault(
            (candidate.start, candidate.end, candidate.char), [],
        ).append(index)
    for indices in groups.values():
        indices.sort(key=lambda index: candidates[index].index)
        variants = {
            value
            for index in indices
            for value in (
                metadata[index]["expected"], *metadata[index]["alternatives"],
            )
            if value
        }
        for label in labels:
            value = observed.get(f"{indices[0]}:{label}", "")
            hits = sorted(
                (match.start(), variant)
                for variant in variants
                for match in re.finditer(re.escape(variant), _plain(value))
            )
            for index in indices:
                ordinal = candidates[index].span_char_ordinal
                if ordinal < len(hits):
                    observed[f"{index}:{label}"] = hits[ordinal][1]


def _extract_samples(video: Path):
    with tempfile.TemporaryDirectory(prefix="polyphone-audio-") as directory:
        audio = Path(directory) / "audio.wav"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
            "-sample_fmt", "s16", str(audio),
        ], check=True, timeout=180)
        import soundfile as sf

        return sf.read(audio, dtype="float32")[0]


def _slice(samples, candidate: Candidate, padding: float):
    left = max(0, round((candidate.start - padding) * 16000))
    right = min(len(samples), round((candidate.end + padding) * 16000))
    return samples[left:right]


def _plain(value: str) -> str:
    return re.sub(r"\s+", "", value or "")
