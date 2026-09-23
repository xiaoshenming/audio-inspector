"""Natural spoken wording for literal function notation in approved narration."""

from __future__ import annotations

import re

ARGUMENT = r"([A-Za-z0-9α-ωΑ-Ω+\- ]{1,32})"
FUNCTION = re.compile(r"\b([A-Za-z])\(" + ARGUMENT + r"\)")
FUNCTION_VALUE = re.compile(r"\b([A-Za-z])\(" + ARGUMENT + r"\)\s*的值")


def _spoken_argument(value: str) -> str:
    return " ".join(value.replace("+", " 加 ").replace("-", " 减 ").split())


def rewrite_function_notation(text: str) -> str:
    text = FUNCTION_VALUE.sub(lambda m: f"{m.group(1)} 在 {_spoken_argument(m.group(2))} 处的值", text)
    return FUNCTION.sub(lambda m: f"{m.group(1)} 在 {_spoken_argument(m.group(2))} 处的值", text)
