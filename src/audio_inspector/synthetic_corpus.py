"""Deterministic math narration cases with seeded defects and clean controls."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

GROUPS = (
    "clean_arithmetic", "clean_explanation", "source_missing_variable",
    "source_missing_operand", "audio_wrong_operator", "audio_wrong_number",
    "audio_wrong_letter", "audio_wrong_unit", "raw_function_notation",
    "benign_equivalence",
)
FILLERS = (
    "先把已知条件和要求的量分别写清楚。",
    "计算时按运算顺序逐步展开，不跳过中间等式。",
    "把得到的数值代回原条件，检查左右两边是否一致。",
    "如果分母为零，就把这种情况从定义域中排除。",
    "画面中的辅助标记用于定位，真正的依据仍是数量关系。",
    "再检查一次单位、符号和字母所代表的对象。",
    "最后把结论写成完整的数学语言，避免只报一个数。",
)


def _core(group: str, index: int) -> tuple[str, str, str]:
    number = 24 + (index * 7) % 53
    other = 3 + index % 9
    left, right, third = (("a", "b", "c"), ("m", "n", "p"),
                          ("x", "y", "z"))[index % 3]
    if group == "clean_arithmetic":
        text = f"已知 {number} 减 {other} 等于 {number - other}，所以原式的值为 {number - other}。"
        return text, text, "intended_clean"
    if group == "clean_explanation":
        text = (f"设线段 {left.upper()}{right.upper()} 长 {number} 厘米，"
                f"线段 {right.upper()}{third.upper()} 长 {other} 厘米，"
                f"两段首尾相接的总长度是 {number + other} 厘米。")
        return text, text, "intended_clean"
    if group == "source_missing_variable":
        correct = f"已知向量 {left} 与 {right} 不共线，求 {left} 加 {right} 的表示方法。"
        broken = f"已知向量与 {right} 不共线，求 {left} 加 {right} 的表示方法。"
        return correct, broken, "seeded_source_defect"
    if group == "source_missing_operand":
        correct = f"把 {left} 的平方加 {other} 等于 {number} 代入方程，求 {left} 的值。"
        broken = f"把的平方加 {other} 等于 {number} 代入方程，求 {left} 的值。"
        return correct, broken, "seeded_source_defect"
    if group == "audio_wrong_operator":
        correct = f"用 {number} 减 {other} 得到 {number - other}，再检查减号两侧的数。"
        spoken = f"用 {number} 加 {other} 得到 {number - other}，再检查加号两侧的数。"
        return correct, spoken, "seeded_audio_mismatch"
    if group == "audio_wrong_number":
        correct = f"由方程解得 {left} 等于 {number}，因此正确答案是 {number}。"
        spoken = f"由方程解得 {left} 等于 {number + 1}，因此正确答案是 {number + 1}。"
        return correct, spoken, "seeded_audio_mismatch"
    if group == "audio_wrong_letter":
        a, b, c = left.upper(), right.upper(), third.upper()
        correct = f"连接线段 {a}{b}，再过点 {c} 作垂线，最后比较两条线段。"
        spoken = f"连接线段 {a}{c}，再过点 {c} 作垂线，最后比较两条线段。"
        return correct, spoken, "seeded_audio_mismatch"
    if group == "audio_wrong_unit":
        correct = f"这个长方形的面积为 {number} 平方米，不能写成长度单位。"
        spoken = f"这个长方形的面积为 {number} 米，不能写成长度单位。"
        return correct, spoken, "seeded_audio_mismatch"
    if group == "raw_function_notation":
        text = (f"已知函数 f(x) 等于 x 的平方加 {other}，"
                f"求 f({number % 5 + 1}) 的值，并说明函数记号的含义。")
        return text, text, "natural_risk_unlabeled"
    correct = "随机事件发生的概率为二分之一，也就是百分之五十。"
    spoken = "随机事件发生的概率为百分之五十，也就是二分之一。"
    return correct, spoken, "intended_clean"


def build_cases(count_per_group: int = 54, seed: int = 20260923) -> list[dict]:
    cases = []
    for group in GROUPS:
        for index in range(count_per_group):
            expected, variant, truth = _core(group, index)
            source = variant if truth == "seeded_source_defect" else expected
            spoken = variant if truth != "seeded_source_defect" else source
            length_tier = ("short", "medium", "long")[index % 3]
            filler_count = {"short": 0, "medium": 3, "long": 12}[length_tier]
            tail = "".join(FILLERS[(index + offset) % len(FILLERS)]
                           for offset in range(filler_count))
            item_id = str(uuid5(NAMESPACE_DNS, f"audio-inspector:{seed}:{group}:{index}"))
            cases.append({"item_id": item_id, "group": group, "index": index,
                          "split": "calibration" if index < 9 else "holdout",
                          "length_tier": length_tier, "truth": truth,
                          "question": expected, "expected_text": expected + tail,
                          "source_text": source + tail, "tts_text": spoken + tail,
                          "tts_model": "qwen-audio-3.0-tts-plus",
                          "voice": "longanlufeng", "rate": 0.9,
                          "seed": (seed + len(cases)) % 65536})
    return cases


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[。！？；])", text) if part.strip()]


def write_corpus(output: Path, cases: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    sources = output / "sources"
    sources.mkdir(exist_ok=True)
    questions = {}
    for case in cases:
        lines = ["class SyntheticScene:", "    def construct(self):"]
        for sentence in _sentences(case["source_text"]):
            lines.extend((f"        with self.voiceover(text={json.dumps(sentence, ensure_ascii=False)}):",
                          "            pass"))
        (sources / f"{case['item_id']}.py").write_text("\n".join(lines) + "\n")
        questions[case["item_id"]] = {"question": case["question"],
                                      "solution_steps": case["expected_text"]}
    metadata = output / "metadata"
    metadata.mkdir(exist_ok=True)
    (metadata / "oracle.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    (metadata / "questions.json").write_text(
        json.dumps(questions, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate labeled synthetic TTS cases")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-group", type=int, default=54)
    parser.add_argument("--seed", type=int, default=20260923)
    args = parser.parse_args()
    if args.per_group < 1:
        parser.error("--per-group must be positive")
    cases = build_cases(args.per_group, args.seed)
    write_corpus(args.output, cases)
    print(json.dumps({"cases": len(cases), "groups": len(GROUPS),
                      "tts_characters": sum(len(x["tts_text"]) for x in cases)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
