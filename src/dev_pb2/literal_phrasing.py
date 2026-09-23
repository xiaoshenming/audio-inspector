"""Natural spoken wording for literal function notation in approved narration."""

from __future__ import annotations

import re

FUNCTION = re.compile(r"\b([A-Za-z])\(([A-Za-z0-9]+)\)")
FUNCTION_VALUE = re.compile(r"\b([A-Za-z])\(([A-Za-z0-9]+)\)\s*的值")


def rewrite_function_notation(text: str) -> str:
    text = FUNCTION_VALUE.sub(lambda m: f"{m.group(1)} 在 {m.group(2)} 处的值", text)
    return FUNCTION.sub(lambda m: f"{m.group(1)} 在 {m.group(2)} 处的值", text)
