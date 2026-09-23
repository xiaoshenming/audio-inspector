"""Small evidence-only checks for source narration omissions models can normalize away."""

from __future__ import annotations

import re

MISSING_FIRST_SET = re.compile(r"已知集合\s*和集合\s*([A-Z])")
VALUE_AS_FUNCTION = re.compile(
    r"(?:函数\s*)?([fgh])\s*在\s*[^，。；]{1,20}?处的值\s*(是|为)\s*([奇偶])函数",
    re.IGNORECASE,
)
VALUE_TRANSFORM = re.compile(
    r"(将|把)\s*(?:函数\s*)?([fgh])\s*在\s*[^，。；]{1,20}?处的值\s*化为",
    re.IGNORECASE,
)
MISSING_PERPENDICULAR_OBJECT = re.compile(
    r"\b([A-Z]{2,3})\s*垂直且等于\s*([A-Z]{2,3})\b"
)


def missing_set_label(lines: list[dict], context: dict) -> list[dict]:
    question = str(context.get("question") or context.get("problem_text") or "")
    if not re.search(r"集合\s*\$?\s*A\b", question):
        return []
    issues = []
    for row in lines:
        for match in MISSING_FIRST_SET.finditer(row["text"]):
            if match.group(1) != "B":
                continue
            issues.append({"category": "source_missing_object", "line": row["line"],
                           "source_quote": match.group(),
                           "source_text": row["text"],
                           "suggested_reading": "已知集合 A 和集合 B",
                           "why": "题干明确给出集合 A、B，旁白在第一个集合后漏掉 A。",
                           "confidence": "high", "detector": "set_label_pattern_v1"})
    return issues


def function_value_misphrasing(lines: list[dict]) -> list[dict]:
    issues = []
    for row in lines:
        for match in VALUE_AS_FUNCTION.finditer(row["text"]):
            issues.append({"category": "source_wrong_expression", "line": row["line"],
                           "source_quote": match.group(), "source_text": row["text"],
                           "suggested_reading": f"函数 {match.group(1)} {match.group(2)}{match.group(3)}函数",
                           "why": "函数值是数值，不能被说成奇函数或偶函数。",
                           "confidence": "high", "detector": "function_value_phrase_v1"})
        for match in VALUE_TRANSFORM.finditer(row["text"]):
            issues.append({"category": "source_wrong_expression", "line": row["line"],
                           "source_quote": match.group(), "source_text": row["text"],
                           "suggested_reading": f"{match.group(1)}函数 {match.group(2)} 的表达式化为",
                           "why": "此处化简的是函数表达式，不宜把单个函数值作为化简对象。",
                           "confidence": "medium", "detector": "function_value_phrase_v1"})
    return issues


def missing_perpendicular_object(lines: list[dict]) -> list[dict]:
    issues = []
    for row in lines:
        for match in MISSING_PERPENDICULAR_OBJECT.finditer(row["text"]):
            left, right = match.groups()
            issues.append({"category": "source_missing_object", "line": row["line"],
                           "source_quote": match.group(), "source_text": row["text"],
                           "suggested_reading": f"{left} 垂直于 {right}，且 {left} 等于 {right}",
                           "why": "垂直关系缺少“于”及对应对象，和长度相等条件混在一起。",
                           "confidence": "high", "detector": "perpendicular_object_pattern_v1"})
    return issues
