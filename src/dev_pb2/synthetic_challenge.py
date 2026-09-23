"""A new-phrasing 60-case challenge set after the baseline format audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

from .synthetic_corpus import write_corpus

GROUPS = ("challenge_source_missing", "challenge_audio_operator",
          "challenge_audio_number", "challenge_audio_letter",
          "challenge_audio_unit", "challenge_clean")
FILLERS = (
    "先用题目给出的关系定位所求对象。",
    "每一步都要保留原来的等量条件。",
    "图上标记只说明位置，计算还要依据已知数值。",
    "把中间结果放回原式进行检验。",
    "最后核对数字、单位和符号是否前后一致。",
    "这个步骤完成后才能写出最终结论。",
    "若条件不满足，就不能使用刚才的推导。",
    "我们再从相反方向验算一次。",
)


def _phrases(group: str, index: int) -> tuple[str, str, str]:
    number = 31 + (index * 11) % 47
    other = 4 + index % 9
    p, q, r = (("A", "B", "C"), ("P", "Q", "R"),
               ("D", "E", "F"))[index % 3]
    if group == "challenge_source_missing":
        correct = f"在三角形 {p}{q}{r} 中，点 {p} 是边 {q}{r} 的中点，求线段 {p}{q} 的长度。"
        broken = f"在三角形 {p}{q}{r} 中，点是边 {q}{r} 的中点，求线段 {p}{q} 的长度。"
        return correct, broken, "seeded_source_defect"
    if group == "challenge_audio_operator":
        correct = f"从 {number} 中减去 {other}，结果是 {number - other}，注意这是减法。"
        spoken = f"把 {other} 加到 {number} 上，结果是 {number - other}，注意这是加法。"
        return correct, spoken, "seeded_audio_mismatch"
    if group == "challenge_audio_number":
        correct = f"根据角的关系，角 {p}{q}{r} 的度数是 {number} 度。"
        spoken = f"根据角的关系，角 {p}{q}{r} 的度数是 {number + 3} 度。"
        return correct, spoken, "seeded_audio_mismatch"
    if group == "challenge_audio_letter":
        correct = f"线段 {p}{q} 平行于线段 {q}{r}，先画出这两条线段。"
        spoken = f"线段 {p}{r} 平行于线段 {q}{r}，先画出这两条线段。"
        return correct, spoken, "seeded_audio_mismatch"
    if group == "challenge_audio_unit":
        correct = f"这个立体图形的体积为 {number} 立方厘米，单位是体积单位。"
        spoken = f"这个立体图形的体积为 {number} 平方厘米，单位是面积单位。"
        return correct, spoken, "seeded_audio_mismatch"
    text = f"用 {number} 减 {other}，可得 {number - other}，将结果代回原条件核验。"
    return text, text, "intended_clean"


def build_cases(seed: int = 20260924) -> list[dict]:
    cases = []
    for group in GROUPS:
        for index in range(10):
            correct, variant, truth = _phrases(group, index)
            source = variant if truth == "seeded_source_defect" else correct
            spoken = variant if truth != "seeded_source_defect" else source
            tier = ("short", "medium", "long")[index % 3]
            count = {"short": 0, "medium": 2, "long": 8}[tier]
            filler = "".join(FILLERS[(index + offset) % len(FILLERS)] for offset in range(count))
            item_id = str(uuid5(NAMESPACE_DNS, f"audio-inspector:{seed}:{group}:{index}"))
            cases.append({"item_id": item_id, "group": group, "index": index,
                          "split": "holdout", "length_tier": tier, "truth": truth,
                          "question": correct, "expected_text": correct + filler,
                          "source_text": source + filler, "tts_text": spoken + filler,
                          "tts_model": "qwen-audio-3.0-tts-plus", "voice": "longanlufeng",
                          "rate": 0.9, "seed": (seed + len(cases)) % 65536})
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate new-phrasing synthetic challenge cases")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = build_cases()
    write_corpus(args.output, cases)
    print(json.dumps({"cases": len(cases), "tts_characters": sum(len(x["tts_text"])
                                                          for x in cases)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
