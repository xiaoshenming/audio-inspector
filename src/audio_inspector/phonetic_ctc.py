"""现成普通话 phonetic CTC 模型的批量推理与确定性读音比较。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TONE_MARKS = {"ˊ": "2", "ˇ": "3", "ˋ": "4"}


@dataclass(frozen=True)
class PhoneticClip:
    clip_id: str
    samples: object


class PhoneticCtc:
    def __init__(self, model_dir: Path, *, device: str = "cuda") -> None:
        import torch
        from transformers import AutoModelForCTC, AutoProcessor

        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable")
        self.torch = torch
        self.device = device
        self.dtype = torch.float16 if device.startswith("cuda") else torch.float32
        self.processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
        self.model = AutoModelForCTC.from_pretrained(
            model_dir, local_files_only=True, torch_dtype=self.dtype,
        ).to(device).eval()

    def transcribe(self, clips: list[PhoneticClip], *, batch_size: int = 16) -> dict[str, str]:
        outputs: dict[str, str] = {}
        for offset in range(0, len(clips), batch_size):
            batch = clips[offset:offset + batch_size]
            inputs = self.processor(
                [clip.samples for clip in batch], sampling_rate=16000,
                return_tensors="pt", padding=True,
            )
            values = inputs.input_values.to(self.device, dtype=self.dtype)
            mask = inputs.get("attention_mask")
            if mask is not None:
                mask = mask.to(self.device)
            with self.torch.inference_mode():
                logits = self.model(values, attention_mask=mask).logits
            texts = self.processor.batch_decode(logits.argmax(dim=-1))
            outputs.update((clip.clip_id, text) for clip, text in zip(batch, texts))
        return outputs


def expected_zhuyin(text: str, expected_pinyin: list[str]) -> str | None:
    """利用 pypinyin 的异读表，把 LLM 数字拼音转换为模型的修改版注音。"""
    from pypinyin import Style, pinyin

    lookup: dict[str, str] = {}
    for char in text:
        tones = pinyin(char, style=Style.TONE3, heteronym=True, neutral_tone_with_five=True)[0]
        zhuyin = pinyin(char, style=Style.BOPOMOFO, heteronym=True)[0]
        lookup.update((_normalize_pinyin(a), _model_zhuyin(b, a)) for a, b in zip(tones, zhuyin))
    tokens = [lookup.get(_normalize_pinyin(item)) for item in expected_pinyin]
    return "".join(tokens) if tokens and all(tokens) else None


def alternative_zhuyin(text: str, target_indices: list[int], readings: list[list[str]]) -> list[str]:
    """把词典中的合法异读转换为模型注音，供显式替代读音确认。"""
    alternatives = []
    for index, values in zip(target_indices, readings):
        if index < 0 or index >= len(text):
            continue
        for value in values:
            converted = expected_zhuyin(text[index], [value])
            if converted and converted not in alternatives:
                alternatives.append(converted)
    return alternatives


def compare_windows(
    expected: str | None, outputs: list[str], alternatives: list[str] | None = None,
) -> tuple[str, str | None]:
    """至少两窗明确读出同一合法异读才判错；漏字和乱码保持 uncertain。"""
    if not expected:
        return "uncertain", None
    valid = [re.sub(r"\s+", "", value) for value in outputs if value.strip()]
    if len(valid) < 2:
        return "uncertain", None
    matches = sum(expected in value for value in valid)
    if matches >= 2:
        return "passed", None
    for alternative in alternatives or []:
        if alternative not in expected and sum(alternative in value for value in valid) >= 2:
            return "confirmed_issue", alternative
    return "uncertain", None


def _model_zhuyin(value: str, pinyin_value: str) -> str:
    tone = "5" if "˙" in value else next(
        (_TONE_MARKS[mark] for mark in _TONE_MARKS if mark in value), "1"
    )
    plain = value.replace("˙", "")
    for mark in _TONE_MARKS:
        plain = plain.replace(mark, "")
    normalized = _normalize_pinyin(pinyin_value)
    if normalized.startswith("y") and plain.startswith(("ㄧ", "ㄩ")):
        plain = "j" + plain
    return plain + tone


def _normalize_pinyin(value: str) -> str:
    return value.lower().replace("ü", "v").replace("u:", "v").strip()
