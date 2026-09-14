"""从生成源码提取期望旁白，不执行用户代码。"""

from __future__ import annotations

import ast


def extract_expected_voiceover(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""
    parts: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_voiceover(node.func):
            continue
        text = _keyword_text(node, "text")
        if text:
            parts.append(text.strip())
    return "".join(parts)[:20000]


def _is_voiceover(func: ast.expr) -> bool:
    return isinstance(func, ast.Attribute) and func.attr == "voiceover"


def _keyword_text(node: ast.Call, name: str) -> str:
    for keyword in node.keywords:
        if keyword.arg != name:
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
        if isinstance(keyword.value, ast.JoinedStr):
            return "".join(
                part.value for part in keyword.value.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
    return ""
