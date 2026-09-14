"""多音字批处理的文本、时间轴与候选准备。"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .expected_text import extract_expected_voiceover

_PLAIN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


@dataclass(frozen=True)
class TimelineChar:
    char: str
    start: float
    end: float


@dataclass(frozen=True)
class Candidate:
    index: int
    char: str
    context: str
    expected_pinyin: str
    alternative_pinyin: tuple[str, ...]
    start: float
    end: float
    priority: bool = False
    span_char_ordinal: int = 0


def load_expected_text(source_path: Path, subtitle_path: Path | None) -> str:
    if subtitle_path and subtitle_path.is_file():
        timeline = parse_vtt(subtitle_path)
        if timeline:
            return "".join(item.char for item in timeline)
    if source_path.is_file():
        text = extract_expected_voiceover(source_path.read_text(encoding="utf-8"))
        if text:
            return text
    return ""


def load_timeline(item: dict, stt_roots: list[Path]) -> list[TimelineChar]:
    subtitle = Path(str(item.get("subtitle_path") or ""))
    if subtitle.is_file():
        timeline = parse_vtt(subtitle)
        if timeline:
            return timeline
    key = f"{item['template']}-{item['video_id']}.json"
    for root in stt_roots:
        path = root / key
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        segments = payload.get("evidence", {}).get("transcript_segments") or []
        timeline = segments_to_timeline(segments)
        if timeline:
            return timeline
    return []


def parse_vtt(path: Path) -> list[TimelineChar]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    timeline: list[TimelineChar] = []
    index = 0
    while index < len(lines):
        if "-->" not in lines[index]:
            index += 1
            continue
        left, right = (part.strip().split()[0] for part in lines[index].split("-->"))
        start, end = _timestamp(left), _timestamp(right)
        index += 1
        text_parts = []
        while index < len(lines) and lines[index].strip():
            text_parts.append(re.sub(r"<[^>]+>", "", lines[index]))
            index += 1
        timeline.extend(_spread("".join(text_parts), start, end, preserve_span=True))
    return timeline


def segments_to_timeline(segments: list[dict]) -> list[TimelineChar]:
    timeline: list[TimelineChar] = []
    for segment in segments:
        timeline.extend(_spread(
            str(segment.get("text") or ""),
            float(segment.get("start") or 0),
            float(segment.get("end") or 0),
            preserve_span=True,
        ))
    return timeline


def build_candidates(
    expected_text: str,
    timeline: list[TimelineChar],
    g2pw_readings: list[str | None],
    *,
    ignored_chars: set[str],
    risk_phrases: dict[str, tuple[str, ...]] | None = None,
) -> list[Candidate]:
    from pypinyin import Style, pinyin

    expectations = _risk_expectations(expected_text, risk_phrases or {})
    plain_expected = "".join(_PLAIN.findall(expected_text))
    source_indices = [i for i, char in enumerate(expected_text) if _PLAIN.fullmatch(char)]
    if len(g2pw_readings) != len(expected_text):
        raise ValueError("G2PW result length differs from source text")
    mapped = align_timeline(plain_expected, timeline)
    candidates: list[Candidate] = []
    for plain_index, source_index in enumerate(source_indices):
        char = expected_text[source_index]
        if char in ignored_chars or not re.fullmatch(r"[\u4e00-\u9fff]", char):
            continue
        readings = {
            _normalize(value)
            for value in pinyin(
                char, style=Style.TONE3, heteronym=True,
                neutral_tone_with_five=True,
            )[0]
            if value
        }
        g2pw_expected = _normalize(g2pw_readings[source_index] or "")
        default = _normalize(pinyin(
            char, style=Style.TONE3, heteronym=False,
            neutral_tone_with_five=True,
        )[0][0])
        choices = expectations.get(source_index, [])
        explicit = [reading for reading, source in choices if source == "incident_lexicon"]
        phrase = {reading for reading, source in choices if source == "pypinyin_phrase"}
        incident_char = any(source == "incident_char" for _, source in choices)
        if explicit:
            expected = explicit[0]
        elif (g2pw_expected in phrase or incident_char) and g2pw_expected != default:
            expected = g2pw_expected
        else:
            continue
        alternatives = tuple(sorted(readings - {expected}))
        location = mapped.get(plain_index)
        if not expected or not alternatives or location is None:
            continue
        start = max(0, source_index - 8)
        end = min(len(expected_text), source_index + 9)
        candidates.append(Candidate(
            index=source_index,
            char=char,
            context=expected_text[start:end],
            expected_pinyin=expected,
            alternative_pinyin=alternatives,
            start=location.start,
            end=location.end,
            priority=bool(explicit or incident_char),
            span_char_ordinal=sum(
                1
                for earlier in range(plain_index)
                if plain_expected[earlier] == char
                and mapped.get(earlier) == location
            ),
        ))
    return candidates


def _risk_expectations(
    text: str, extra_phrases: dict[str, tuple[str, ...]],
) -> dict[int, list[tuple[str, str]]]:
    """短语词典与事故词库共同给出候选，拒绝单字冷门异读。"""
    from pypinyin import Style, pinyin
    from pypinyin.phrases_dict import phrases_dict

    expectations: dict[int, list[tuple[str, str]]] = {}
    incident_chars = set()
    for phrase, readings in extra_phrases.items():
        for char, reading in zip(phrase, readings):
            if not re.fullmatch(r"[\u4e00-\u9fff]", char):
                continue
            default = pinyin(
                char, style=Style.TONE3, heteronym=False,
                neutral_tone_with_five=True,
            )[0][0]
            if _normalize(reading) != _normalize(default):
                incident_chars.add(char)
    for index, char in enumerate(text):
        if char in incident_chars:
            expectations.setdefault(index, []).append(("", "incident_char"))
    for start in range(len(text)):
        for length in range(2, 7):
            phrase = text[start:start + length]
            explicit = extra_phrases.get(phrase)
            if phrase not in phrases_dict and not explicit:
                continue
            readings = explicit or tuple(
                values[0] for values in pinyin(
                    phrase, style=Style.TONE3, heteronym=False,
                    neutral_tone_with_five=True,
                )
            )
            if len(readings) != len(phrase):
                continue
            source = "incident_lexicon" if explicit else "pypinyin_phrase"
            for offset, (char, reading) in enumerate(zip(phrase, readings)):
                if not re.fullmatch(r"[\u4e00-\u9fff]", char):
                    continue
                values = pinyin(char, style=Style.TONE3, heteronym=True)[0]
                if len(set(values)) > 1:
                    expectations.setdefault(start + offset, []).append(
                        (_normalize(reading), source)
                    )
    return expectations


def align_timeline(
    expected: str, timeline: list[TimelineChar],
) -> dict[int, TimelineChar]:
    observed = "".join(item.char for item in timeline)
    matcher = difflib.SequenceMatcher(None, expected.lower(), observed.lower(), autojunk=False)
    mapping: dict[int, TimelineChar] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = timeline[block.b + offset]
    return mapping


def _spread(
    text: str, start: float, end: float, *, preserve_span: bool = False,
) -> list[TimelineChar]:
    chars = _PLAIN.findall(text)
    if not chars:
        return []
    if preserve_span:
        return [TimelineChar(char, start, end) for char in chars]
    width = max(0.02, end - start) / len(chars)
    return [
        TimelineChar(char, start + index * width, start + (index + 1) * width)
        for index, char in enumerate(chars)
    ]


def _timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    return int(parts[-3]) * 3600 + int(parts[-2]) * 60 + float(parts[-1])


def _normalize(value: str) -> str:
    return value.lower().replace("ü", "v").replace("u:", "v").strip()
