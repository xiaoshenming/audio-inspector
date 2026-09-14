"""TTS 输入与归档检查共享的发音清单合同。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PronunciationEntry:
    text: str
    pinyin: str
    phones: tuple[str, ...]
    source: str
    confidence: float


def build_manifest(entries: Iterable[PronunciationEntry]) -> dict:
    retained = []
    for entry in entries:
        if not entry.text or not entry.phones:
            continue
        item = asdict(entry)
        item["phones"] = list(entry.phones)
        retained.append(item)
    return {
        "schema_version": "audio-inspector.pronunciation-manifest.v1",
        "entries": retained,
    }


def hot_fix_payload(manifest: dict) -> dict:
    """只把已确认读音发送给 CosyVoice，低置信候选留给人工复核。"""
    pronunciation = []
    for entry in manifest.get("entries", []):
        if float(entry.get("confidence", 0)) < 1.0:
            continue
        pinyin = str(entry.get("pinyin") or "")
        if pinyin:
            pronunciation.append({str(entry["text"]): pinyin})
    return {"pronunciation": pronunciation}
