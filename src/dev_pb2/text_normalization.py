"""脚本与转写比较使用的通用文本归一化。"""

from __future__ import annotations

import re
import warnings

from .phonetics import phonetically_equivalent


def comparison_text(value: str) -> str:
    text = value.lower().translate(
        str.maketrans(
            "們時圖認絲綢線橫歐亞陸從長發經過拋觀",
            "们时图认丝绸线横欧亚陆从长发经过抛观",
        )
    )
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"百分之\1", text)
    text = re.sub(r"(?<![\dA-Za-z.)])-\s*(\d+(?:\.\d+)?)", r"负\1", text)
    text = text.replace("π", "派").replace("=", "等于").replace("+", "加")
    text = text.replace("等号", "等于").replace("摄氏度", "度").replace("℃", "度")
    text = _normalize_numbers(text)
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    substitutions = (
        (r"第[二2]", "第2"),
        (r"[二2](?=次函数|次方|阶|元|项|进制|分之一|号|月|年级)", "2"),
        (r"[两2](?=个|条|只|种|边|点|端|位|根|组|类|侧)", "2"),
    )
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text)
    return text


def phonetic_replacement_equal(tag: str, expected: str, actual: str) -> bool:
    return tag == "replace" and phonetically_equivalent(expected, actual)


def _normalize_numbers(text: str) -> str:
    try:
        from cn2an import transform  # type: ignore
    except ImportError:
        # Number normalization improves matching but is not required for the
        # analyzer to produce evidence in lightweight/offline environments.
        return text.translate(str.maketrans("零〇一二三四五六七八九", "00123456789"))

    text = re.sub(r"两(?=[百千万亿])", "二", text)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return transform(text, "cn2an")
