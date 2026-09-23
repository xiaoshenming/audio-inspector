"""Resumable isolated closure trial over previously shortlisted real videos."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from collections import Counter
from pathlib import Path

from .decisions import decide
from .literal_phrasing import rewrite_function_notation
from .pipeline import run
from .repair_media import rebuild


def _literal_rewrite(text: str) -> str:
    return rewrite_function_notation(text)


def _edits(issues: list[dict]) -> list[dict]:
    edits = []
    for issue in sorted(issues, key=lambda row: row["category"] == "audio_literal_formula"):
        proposed = str(issue.get("proposed_text") or "").strip()
        if issue["category"] == "audio_literal_formula":
            proposed = _literal_rewrite(issue["original_text"])
            if proposed == issue["original_text"]:
                raise ValueError("literal_formula_has_no_safe_rewrite")
        if not proposed:
            raise ValueError("issue_has_no_text_proposal")
        edits.append({"issue_id": issue["issue_id"], "new_text": proposed})
    return edits


def _case(case: dict, work_root: Path, output: Path,
          api_key: str, tts_endpoint: str,
          retry_statuses: set[str] | None = None) -> dict:
    item_id = case["request"]["item_id"]
    folder = output / "cases" / item_id
    folder.mkdir(parents=True, exist_ok=True)
    result_file = folder / "result.json"
    if result_file.is_file():
        previous = json.loads(result_file.read_text())
        if previous.get("terminal") and previous.get("status") not in (retry_statuses or set()):
            return previous
    result: dict = {"item_id": item_id, "terminal": True,
                    "approval_mode": "simulated_model_proposal",
                    "original_priority": case.get("original_priority"),
                    "original_categories": case.get("original_categories") or []}
    try:
        before = run(case["request"], work_root)
        result["before_status"] = before["status"]
        result["before_issues"] = len(before["issues"])
        result["before_categories"] = sorted({row["category"] for row in before["issues"]})
        if before["status"] == "failed_open":
            result["status"] = "inspection_failed"
            result["terminal"] = False
        elif before["status"] == "clean":
            result["status"] = "clean_initial"
        elif not all(Path(case[name]).is_file() for name in ("unburned", "source_pack")):
            result["status"] = "unsupported_assets"
        else:
            edits = _edits(before["issues"])
            decision = decide(before, Path(case["request"]["source_path"]),
                              "dev-pb2-batch-simulation", "approve_repair", edits)
            (folder / "decision.json").write_text(json.dumps(decision,
                ensure_ascii=False, indent=2) + "\n")
            repaired = rebuild(before, decision,
                               video=Path(case["request"]["video_path"]),
                               unburned=Path(case["unburned"]),
                               subtitle=Path(case["request"]["subtitle_path"]),
                               source_pack=Path(case["source_pack"]),
                               output=folder / "repaired", api_key=api_key,
                               tts_endpoint=tts_endpoint)
            next_request = {**case["request"],
                            "revision_id": case["request"]["revision_id"]
                            + ":pb2:" + decision["idempotency_key"][:12],
                            "video_path": repaired["video_path"],
                            "video_sha256": repaired["video_sha256"],
                            "source_path": repaired["source_path"],
                            "source_sha256": repaired["source_sha256"],
                            "subtitle_path": repaired["subtitle_path"]}
            after = run(next_request, work_root)
            result["status"] = ("closure_clean" if after["status"] == "clean"
                                else "closure_candidate" if after["status"] == "candidate"
                                else "reinspection_failed")
            if result["status"] == "reinspection_failed":
                result["terminal"] = False
            result["after_status"] = after["status"]
            result["after_issues"] = len(after["issues"])
            result["after_categories"] = sorted({row["category"] for row in after["issues"]})
            result["video_path"] = repaired["video_path"]
            result["video_sha256"] = repaired["video_sha256"]
            result["tts_calls"] = len(repaired["tts"])
    except Exception as exc:  # noqa: BLE001 - preserve one-row failure evidence.
        reason = str(exc)
        if "replacement_duration_requires_scene_rerender" in reason:
            result["status"] = "needs_full_scene_rerender"
        elif ("subtitle_cue" in reason or "subtitle_timeline" in reason):
            result["status"] = "unsupported_subtitle_alignment"
        elif any(code in reason for code in ("issue_has_no_text_proposal",
                                            "voiceover_target_not_unique",
                                            "approved_voiceover_not_unique",
                                            "overlapping_voiceover_edits",
                                            "literal_formula_has_no_safe_rewrite")):
            result["status"] = "needs_manual_repair_text"
        else:
            result["status"] = "repair_failed"
            result["terminal"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def run_batch(batch: Path, work_root: Path, output: Path,
              *, workers: int = 2, item_ids: set[str] | None = None,
              retry_statuses: set[str] | None = None) -> dict:
    cases = json.loads(batch.read_text())["cases"]
    if item_ids is not None:
        cases = [case for case in cases if case["request"]["item_id"] in item_ids]
    if workers < 1 or workers > 4:
        raise ValueError("workers_must_be_between_1_and_4")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_case, case, work_root, output,
                               os.environ["DASHSCOPE_API_KEY"],
                               os.environ["DASHSCOPE_TTS_ENDPOINT"], retry_statuses)
                   for case in cases]
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            results.append(row)
            print(f"pb2_batch {len(results)}/{len(cases)} {row['item_id']} "
                  f"{row['status']}", flush=True)
    counts = Counter(row["status"] for row in results)
    summary = {"schema_version": "dev-pb2.batch-eval.v1",
               "approval_mode": "simulated_model_proposal",
               "total": len(cases), "counts": dict(counts),
               "literal_cases": sum("audio_literal_formula" in row["original_categories"]
                                    for row in results),
               "literal_closure_clean": sum(
                   "audio_literal_formula" in row["original_categories"]
                   and row["status"] == "closure_clean" for row in results),
               "closure_rate_among_initial_candidates": round(
                   counts["closure_clean"] /
                   max(1, sum(row.get("before_status") == "candidate" for row in results)), 4),
               "results": sorted(results, key=lambda row: row["item_id"])}
    summary_name = "summary.json" if item_ids is None else "summary-subset.json"
    (output / summary_name).write_text(json.dumps(summary, ensure_ascii=False,
                                             indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Trial whole-module closure on a real shortlist")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--item-id", action="append")
    parser.add_argument("--retry-status", action="append")
    args = parser.parse_args()
    result = run_batch(args.batch, args.work_root, args.output, workers=args.workers,
                       item_ids=set(args.item_id) if args.item_id else None,
                       retry_statuses=set(args.retry_status) if args.retry_status else None)
    print(json.dumps({key: result[key] for key in
                      ("total", "counts", "closure_rate_among_initial_candidates")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
