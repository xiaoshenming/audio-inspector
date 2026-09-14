"""中文读音等价判断；用于过滤 Whisper 的同音字转写差异。"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=4096)
def pronunciation_key(text: str) -> tuple[str, ...]:
    """返回带声调拼音；非汉字原样保留，避免吞掉数字和字母差异。"""
    try:
        from pypinyin import Style, pinyin  # type: ignore
    except ImportError:
        # Preserve the analyzer in minimal worker/test environments.  This
        # conservative table only folds known unambiguous STT homophones.
        aliases = str.maketrans({"县": "线", "农": "浓"})
        return tuple(text.translate(aliases))

    values = pinyin(
        text,
        style=Style.TONE3,
        heteronym=False,
        neutral_tone_with_five=True,
        errors=lambda value: list(value),
    )
    return tuple(str(item[0]).lower() for item in values if item)


def phonetically_equivalent(expected: str, actual: str) -> bool:
    if not expected or not actual:
        return False
    return pronunciation_key(expected) == pronunciation_key(actual)
