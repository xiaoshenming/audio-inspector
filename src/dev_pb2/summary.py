"""Combine local and worker repair attempts without treating candidates as truth."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def summarize(batch: Path, evaluation: Path) -> dict:
    cases = json.loads(batch.read_text())["cases"]
    rows = []
    for case in cases:
        item_id = case["request"]["item_id"]
        folder = evaluation / "cases" / item_id
        first = _load(folder / "result.json")
        iteration = _load(folder / "iterations.json")
        worker = _load(folder / "worker-result.json")
        if worker.get("status") == "closure_clean":
            final = "machine_clean"
            mode = "full_scene_render"
            video = worker.get("video_path")
        elif first.get("status") == "closure_clean":
            final = "machine_clean"
            mode = "local_revoice"
            video = first.get("video_path")
        elif iteration.get("status") == "closure_clean":
            final = "machine_clean"
            mode = "iterated_revoice"
            details = iteration.get("details") or []
            video = next((row.get("video_path") for row in reversed(details)
                          if row.get("after_status") == "clean"), None)
        else:
            final = "needs_review_or_repair"
            mode = None
            video = None
        rows.append({"item_id": item_id, "original_priority": case["original_priority"],
                     "original_categories": case["original_categories"],
                     "initial": first.get("status", "missing"),
                     "iteration": iteration.get("status"),
                     "worker": worker.get("status"),
                     "final": final, "repair_mode": mode, "video_path": video})
    counts = Counter(row["final"] for row in rows)
    modes = Counter(row["repair_mode"] for row in rows if row["repair_mode"])
    literal = [row for row in rows
               if "audio_literal_formula" in row["original_categories"]]
    result = {"schema_version": "dev-pb2.combined-eval.v1",
              "approval_mode": "simulated_model_proposal",
              "staff_review_labels_available": False,
              "total": len(rows), "final_counts": dict(counts),
              "closure_rate": round(counts["machine_clean"] / len(rows), 4),
              "repair_modes": dict(modes),
              "literal_cases": len(literal),
              "literal_machine_clean": sum(row["final"] == "machine_clean"
                                           for row in literal),
              "initial_counts": dict(Counter(row["initial"] for row in rows)),
              "iteration_counts": dict(Counter(row["iteration"] for row in rows
                                       if row["iteration"])),
              "worker_counts": dict(Counter(row["worker"] for row in rows
                                    if row["worker"])),
              "rows": rows}
    (evaluation / "combined-summary.json").write_text(json.dumps(result,
        ensure_ascii=False, indent=2) + "\n")
    lines = ["# 65 条真实终审候选的模块化闭环测试", "",
             "本批由机器建议文字模拟管理员批准，线上复审 SQLite 没有保存的员工标签。",
             "`machine_clean` 仅表示新成片完成且全流程复筛无候选，不能当成人工确认正确。",
             "", "| 指标 | 数量 |", "|---|---:|",
             f"| 重新筛查的视频 | {len(rows)} |",
             f"| 新成片复筛无候选 | {counts['machine_clean']} |",
             f"| 仍需核听或另定修复 | {counts['needs_review_or_repair']} |",
             f"| 函数括号类复筛无候选 | {result['literal_machine_clean']}/{len(literal)} |",
             "", "## 修复路径", ""]
    lines.extend(f"- `{mode}`：{count} 条" for mode, count in sorted(modes.items()))
    lines += ["", "## 未闭环原因", ""]
    reasons = Counter((row["worker"] or row["iteration"] or row["initial"])
                      for row in rows if row["final"] != "machine_clean")
    lines.extend(f"- `{reason}`：{count} 条" for reason, count in sorted(reasons.items()))
    lines += ["", "逐条来源、修复方式和成片路径见 `combined-summary.json`。", ""]
    (evaluation / "combined-report.md").write_text("\n".join(lines))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize isolated real-video closure")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.batch, args.evaluation)
    print(json.dumps({key: result[key] for key in
                      ("total", "final_counts", "closure_rate", "repair_modes",
                       "literal_cases", "literal_machine_clean")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
