"""Run isolated full-scene fallback for cases unsuitable for local revoice."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from collections import Counter
from pathlib import Path

from .batch_eval import _edits
from .decisions import decide
from .pipeline import run
from .source_revision import revise_pack
from .worker_render import render_and_inspect

ELIGIBLE = {"needs_full_scene_rerender", "unsupported_assets",
            "unsupported_subtitle_alignment"}


def _prepare_source(case: dict, folder: Path, work_root: Path) -> tuple[Path, Path]:
    rounds = sorted(folder.glob("round-*/repaired"),
                    key=lambda path: int(path.parent.name.split("-")[-1]), reverse=True)
    for prepared in [*rounds, folder / "repaired"]:
        if (prepared / "source.tar").is_file() and (prepared / "main.py").is_file():
            return prepared / "source.tar", prepared / "main.py"
    before = run(case["request"], work_root)
    if before["status"] != "candidate":
        raise ValueError(f"repair_requires_candidate:{before['status']}")
    edits = _edits(before["issues"])
    decision = decide(before, Path(case["request"]["source_path"]),
                      "dev-pb2-batch-simulation", "approve_repair", edits)
    output = folder / "worker-source"
    main = revise_pack(Path(case["source_pack"]), decision["voiceover_overrides"], output)
    (output / "decision.json").write_text(json.dumps(decision, ensure_ascii=False,
                                                    indent=2) + "\n")
    return output / "source.tar", main


def _one(case: dict, eval_root: Path, work_root: Path) -> dict:
    item_id = case["request"]["item_id"]
    folder = eval_root / "cases" / item_id
    result_file = folder / "worker-result.json"
    if result_file.is_file():
        previous = json.loads(result_file.read_text())
        if previous.get("terminal") and previous.get("status") != "reinspection_failed":
            return previous
    result = {"item_id": item_id, "terminal": True,
              "approval_mode": "simulated_model_proposal"}
    try:
        source_pack, main = _prepare_source(case, folder, work_root)
        closure = render_and_inspect(case["request"], source_pack, main,
                                     folder / "worker-render", work_root)
        result["status"] = ("closure_clean" if closure["reinspection"]["status"]
                            == "clean" else "closure_candidate" if
                            closure["reinspection"]["status"] == "candidate"
                            else "reinspection_failed")
        if result["status"] == "reinspection_failed":
            result["terminal"] = False
        result["render_job_id"] = closure["render"]["render_job_id"]
        result["video_path"] = closure["render"]["video_path"]
        result["video_sha256"] = closure["render"]["video_sha256"]
        result["after_issues"] = len(closure["reinspection"]["issues"])
        result["after_categories"] = sorted({row["category"] for row in
                                             closure["reinspection"]["issues"]})
    except Exception as exc:  # noqa: BLE001 - keep each real case visible.
        reason = str(exc)
        result["status"] = ("needs_manual_repair_text" if any(code in reason for code in
            ("overlapping_voiceover_edits", "voiceover_target_not_unique",
             "issue_has_no_text_proposal")) else "render_failed")
        result["terminal"] = result["status"] != "render_failed"
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def run_batch(batch: Path, eval_root: Path, work_root: Path,
              *, workers: int = 2, item_ids: set[str] | None = None) -> dict:
    if not 1 <= workers <= 4:
        raise ValueError("workers_must_be_between_1_and_4")
    cases = json.loads(batch.read_text())["cases"]
    def eligible(case: dict) -> bool:
        folder = eval_root / "cases" / case["request"]["item_id"]
        path = folder / "result.json"
        if not path.is_file():
            return False
        first = json.loads(path.read_text())["status"]
        if first in ELIGIBLE:
            return True
        iterations = folder / "iterations.json"
        if first != "closure_candidate" or not iterations.is_file():
            return False
        state = json.loads(iterations.read_text())
        details = state.get("details") or []
        return (state.get("status") == "retry_failed" and bool(details)
                and "replacement_duration_requires_scene_rerender"
                in details[-1].get("error", ""))

    selected = [case for case in cases
                if (item_ids is None or case["request"]["item_id"] in item_ids)
                and eligible(case)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, case, eval_root, work_root) for case in selected]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"pb2_worker_batch {len(results)}/{len(selected)} "
                  f"{result['item_id']} {result['status']}", flush=True)
    summary = {"schema_version": "dev-pb2.worker-batch.v1",
               "approval_mode": "simulated_model_proposal",
               "eligible": len(selected),
               "counts": dict(Counter(row["status"] for row in results)),
               "results": sorted(results, key=lambda row: row["item_id"])}
    summary_name = "worker-summary.json" if item_ids is None else "worker-summary-subset.json"
    (eval_root / summary_name).write_text(json.dumps(summary,
        ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Trial full-scene fallback on BatchOps worker")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--eval-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--item-id", action="append")
    args = parser.parse_args()
    result = run_batch(args.batch, args.eval_root, args.work_root,
                       workers=args.workers,
                       item_ids=set(args.item_id) if args.item_id else None)
    print(json.dumps({"eligible": result["eligible"], "counts": result["counts"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
