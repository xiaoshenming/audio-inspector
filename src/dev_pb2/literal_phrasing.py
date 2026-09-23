"""Natural spoken wording for literal function notation in approved narration."""

from __future__ import annotations

import re

ARGUMENT = r"([A-Za-z0-9α-ωΑ-Ω_+\- ]{1,32})"
FUNCTION = re.compile(r"\b([A-Za-z])\(" + ARGUMENT + r"\)")
FUNCTION_VALUE = re.compile(r"\b([A-Za-z])\(" + ARGUMENT + r"\)\s*的值")
FUNCTION_PROPERTY = re.compile(
    r"(?:函数\s*)?([A-Za-z])\(" + ARGUMENT +
    r"\)(?=\s*(?:(?:是|为)\s*[奇偶]函数|的(?:定义域|值域|单调性|极值|零点|图像|最大值|最小值)))"
)
FUNCTION_TRANSFORM = re.compile(r"(将|把)\s*([A-Za-z])\(" + ARGUMENT + r"\)\s*化为")


def _spoken_argument(value: str) -> str:
    value = re.sub(r"([A-Za-z0-9])_(\d+)", r"\1 下标 \2", value)
    return " ".join(value.replace("+", " 加 ").replace("-", " 减 ").split())


def rewrite_function_notation(text: str) -> str:
    text = FUNCTION_TRANSFORM.sub(lambda m: f"{m.group(1)}函数 {m.group(2)} 的表达式化为", text)
    text = FUNCTION_PROPERTY.sub(lambda m: f"函数 {m.group(1)}", text)
    text = FUNCTION_VALUE.sub(lambda m: f"{m.group(1)} 在 {_spoken_argument(m.group(2))} 处的值", text)
    return FUNCTION.sub(lambda m: f"{m.group(1)} 在 {_spoken_argument(m.group(2))} 处的值", text)
