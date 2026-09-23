"""Compare frozen screening results with seeded synthetic case labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

SOURCE_TRUTH = "seeded_source_defect"
AUDIO_TRUTH = "seeded_audio_mismatch"
CLEAN_TRUTH = "intended_clean"


def _items(directory: Path) -> dict[str, dict]:
    if not directory.is_dir():
        return {}
    return {(row := json.loads(path.read_text()))["item_id"]: row
            for path in (directory / "items").glob("*.json")}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _metrics(cases: list[dict]) -> dict:
    source = [x for x in cases if x["truth"] == SOURCE_TRUTH]
    audio = [x for x in cases if x["truth"] == AUDIO_TRUTH]
    positive = source + audio
    clean = [x for x in cases if x["truth"] == CLEAN_TRUTH]
    natural = [x for x in cases if x["truth"] == "natural_risk_unlabeled"]
    flagged_positive = sum(x["candidate"] for x in positive)
    flagged_clean = sum(x["candidate"] for x in clean)
    a_positive = sum(x["priority_a"] for x in positive)
    a_clean = sum(x["priority_a"] for x in clean)
    return {
        "count": len(cases), "seeded_positive": len(positive),
        "intended_clean": len(clean), "natural_unlabeled": len(natural),
        "candidate_videos": sum(x["candidate"] for x in cases),
        "priority_a_videos": sum(x["priority_a"] for x in cases),
        "source_lane_recall": _rate(sum(x["source_candidate"] for x in source), len(source)),
        "audio_lane_recall": _rate(sum(x["audio_candidate"] for x in audio), len(audio)),
        "seeded_any_recall": _rate(flagged_positive, len(positive)),
        "priority_a_recall": _rate(a_positive, len(positive)),
        "intended_clean_flag_rate": _rate(flagged_clean, len(clean)),
        "seeded_precision_proxy": _rate(flagged_positive, flagged_positive + flagged_clean),
        "priority_a_precision_proxy": _rate(a_positive, a_positive + a_clean),
        "natural_candidate_rate": _rate(sum(x["candidate"] for x in natural), len(natural)),
        "by_group": {group: {
            "count": len(rows), "candidate_rate": _rate(sum(x["candidate"] for x in rows), len(rows)),
            "a_rate": _rate(sum(x["priority_a"] for x in rows), len(rows)),
        } for group in sorted({x["group"] for x in cases})
            if (rows := [x for x in cases if x["group"] == group])},
    }


def _markdown(result: dict) -> str:
    def value(number: float | None) -> str:
        return "—" if number is None else f"{number * 100:.1f}%"

    lines = [f"# {result['planned']} 条合成 TTS 样本筛查量化", "",
             f"模型：`{result['tts_model']}` / `{result['voice']}` / 语速 {result['rate']}。",
             "", "| 范围 | 可评估 | 注入缺陷检出 | 正确控制误报 | 注入类查准代理 | A级注入检出 |",
             "|---|---:|---:|---:|---:|---:|"]
    for title, group in (("校准集", result["splits"]["calibration"]),
                         ("留出集", result["splits"]["holdout"]),
                         ("合计", result["overall"])):
        lines.append(f"| {title} | {group['count']} | {value(group['seeded_any_recall'])} | "
                     f"{value(group['intended_clean_flag_rate'])} | "
                     f"{value(group['seeded_precision_proxy'])} | "
                     f"{value(group['priority_a_recall'])} |")
    lines += ["", "## 各类样本进入复核的比例", "",
              "| 类型 | 校准集 | 留出集 | 合计 |", "|---|---:|---:|---:|"]
    groups = sorted(result["overall"]["by_group"])
    for name in groups:
        def group_rate(section: dict, group: str) -> str:
            return value(section["by_group"].get(group, {}).get("candidate_rate"))

        lines.append(f"| `{name}` | {group_rate(result['splits']['calibration'], name)} | "
                     f"{group_rate(result['splits']['holdout'], name)} | "
                     f"{group_rate(result['overall'], name)} |")
    lines += ["", "## 运行覆盖", "",
              "| 阶段 | 完成 | 失败 | 尚缺 |", "|---|---:|---:|---:|"]
    for stage, counts in result["stage_coverage"].items():
        lines.append(f"| {stage} | {counts['completed']} | {counts['failed_open']} | "
                     f"{counts['missing']} |")
    lines += ["", (f"TTS 实际计费字符：{result['provider_usage']['tts_billed_characters']}；"
                   f"合成音频约 {result['provider_usage']['audio_hours']} 小时。"), "",
              "## 判读边界", "",
              "- 完成率和失败数见 `benchmark-results.json`；未完成样本不记成无问题。",
              "- “注入缺陷检出”与“查准代理”只对人为改写的文本输入有效，不能直接外推为生产真实 TTS 准确率。",
              "- `raw_function_notation` 没有预置真假，须人工核听；它不进入注入类查准率分母。",
              "- 正确控制样本若出现自然读错，也可能被误计为机器误报，需抽样人工标注。",
              "- 本语料每组使用有限模板与数值变化；留出集检验同分布稳定性，不代表全部数学题型。",
              ""]
    return "\n".join(lines)


def evaluate(root: Path) -> dict:
    oracle = json.loads((root / "metadata/oracle.json").read_text())
    tts = {row["item_id"]: row for path in (root / "metadata/tts-results").glob("*.json")
           if (row := json.loads(path.read_text()))}
    qwen = _items(root / "asr-qwen")
    source = _items(root / "semantic-source")
    audio = _items(root / "semantic-audio")
    literal = _items(root / "literal-reading")
    literal_asr = _items(root / "literal-asr-targeted")
    candidates = {row["item_id"]: row for row in json.loads(
        (root / "screening-review/candidates.json").read_text())}
    complete = []
    incomplete = Counter()
    for case in oracle:
        item_id = case["item_id"]
        stages = {"tts": tts.get(item_id), "qwen": qwen.get(item_id),
                  "source": source.get(item_id), "audio": audio.get(item_id),
                  "literal": literal.get(item_id)}
        failures = [name for name, stage in stages.items()
                    if not stage or stage.get("status") != "completed"]
        if failures:
            incomplete.update(failures)
            continue
        candidate = candidates.get(item_id) or {}
        complete.append({**case, "candidate": bool(candidate),
                         "priority_a": candidate.get("priority") == "A",
                         "source_candidate": bool(candidate.get("source_issues")),
                         "audio_candidate": bool(candidate.get("audio_issues"))})
    groups = {split: _metrics([row for row in complete if row["split"] == split])
              for split in ("calibration", "holdout")}
    stages = {"tts": tts, "qwen_asr": qwen, "source_review": source,
              "audio_review": audio, "literal_asr": literal_asr,
              "literal_review": literal}
    coverage = {name: {
        "completed": sum(row.get("status") == "completed" for row in items.values()),
        "failed_open": sum(row.get("status") not in {"completed", None}
                           for row in items.values()),
        "missing": len(oracle) - len(items),
    } for name, items in stages.items()}
    result = {"planned": len(oracle), "evaluable": len(complete),
              "tts_model": oracle[0]["tts_model"] if oracle else "",
              "voice": oracle[0]["voice"] if oracle else "",
              "rate": oracle[0]["rate"] if oracle else None,
              "stage_coverage": coverage,
              "provider_usage": {
                  "tts_billed_characters": sum(row.get("characters_billed") or 0
                                               for row in tts.values()),
                  "audio_hours": round(sum(row.get("duration_seconds") or 0
                                           for row in tts.values()) / 3600, 2),
                  "qwen_tokens": sum((chunk.get("usage") or {}).get("total_tokens") or 0
                                     for row in qwen.values() for chunk in row.get("chunks") or []),
                  "deepseek_input_tokens": sum((row.get("usage") or {}).get("input_tokens") or 0
                                               for items in (source, audio) for row in items.values()),
              },
              "incomplete_by_stage": dict(incomplete),
              "overall": _metrics(complete), "splits": groups,
              "by_length": {tier: _metrics([row for row in complete if row["length_tier"] == tier])
                            for tier in ("short", "medium", "long")},
              "truth_note": ("注入标签只证明输入/旁白被人为改动，不自动证明最终音频"
                             "真实读错；自然风险样本无预设真假，需人工核听。")}
    report = root / "screening-review/benchmark-results.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (root / "screening-review/benchmark-report.md").write_text(_markdown(result))
    with (root / "screening-review/benchmark-cases.csv").open(
            "w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["item_id", "group", "split", "length_tier", "truth",
                         "candidate", "priority_a", "source_candidate", "audio_candidate"])
        for row in complete:
            writer.writerow([row[key] for key in
                             ("item_id", "group", "split", "length_tier", "truth",
                              "candidate", "priority_a", "source_candidate", "audio_candidate")])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate seeded synthetic screening cases")
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.root)
    print(json.dumps({"planned": result["planned"], "evaluable": result["evaluable"],
                      "overall": result["overall"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
