"""Reinspect and retry newly surfaced issues in an isolated batch trial."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from collections import Counter
from pathlib import Path

from .batch_eval import _edits
from .decisions import decide
from .pipeline import run
from .repair_media import rebuild


def _next_request(request: dict, decision: dict, repair: dict) -> dict:
    return {**request, "revision_id": request["revision_id"] + ":pb2:"
            + decision["idempotency_key"][:12],
            "video_path": repair["video_path"],
            "source_path": repair["source_path"],
            "subtitle_path": repair["subtitle_path"],
            "video_sha256": repair["video_sha256"],
            "source_sha256": repair["source_sha256"]}


def _iterate(case: dict, eval_root: Path, work_root: Path,
             max_rounds: int, api_key: str, tts_endpoint: str) -> dict:
    item_id = case["request"]["item_id"]
    folder = eval_root / "cases" / item_id
    first_result = json.loads((folder / "result.json").read_text())
    if first_result["status"] != "closure_candidate":
        return {"item_id": item_id, "status": "not_eligible", "rounds": 1}
    result_file = folder / "iterations.json"
    if result_file.is_file():
        previous = json.loads(result_file.read_text())
        if previous.get("terminal"):
            return previous
    request = case["request"]
    prior_dir = folder / "repaired"
    rounds = []
    for round_number in range(2, max_rounds + 1):
        prior_decision = json.loads((folder / "decision.json" if round_number == 2
                                    else folder / f"round-{round_number - 1}/decision.json")
                                    .read_text())
        prior_repair = json.loads((prior_dir / "repair-receipt.json").read_text())
        request = _next_request(request, prior_decision, prior_repair)
        state = run(request, work_root)
        if state["status"] == "clean":
            outcome = "closure_clean"
            break
        if state["status"] != "candidate":
            outcome = "reinspection_failed"
            break
        try:
            edits = _edits(state["issues"])
            by_id = {issue["issue_id"]: issue for issue in state["issues"]}
            if all(edit["new_text"] == by_id[edit["issue_id"]]["original_text"]
                   for edit in edits):
                outcome = "persistent_audio_candidate"
                break
            decision = decide(state, Path(request["source_path"]),
                              "dev-pb2-batch-simulation", "approve_repair", edits)
            round_dir = folder / f"round-{round_number}"
            round_dir.mkdir(exist_ok=True)
            (round_dir / "decision.json").write_text(json.dumps(decision,
                ensure_ascii=False, indent=2) + "\n")
            repair = rebuild(state, decision, video=Path(request["video_path"]),
                             unburned=prior_dir / "corrected-unburned.mp4",
                             subtitle=Path(request["subtitle_path"]),
                             source_pack=Path(prior_repair["source_pack_path"]),
                             output=round_dir / "repaired", api_key=api_key,
                             tts_endpoint=tts_endpoint)
            new_state = run(_next_request(request, decision, repair), work_root)
            rounds.append({"round": round_number, "before_issues": len(state["issues"]),
                           "after_issues": len(new_state["issues"]),
                           "after_status": new_state["status"],
                           "video_path": repair["video_path"]})
            prior_dir = round_dir / "repaired"
            outcome = ("closure_clean" if new_state["status"] == "clean"
                       else "closure_candidate" if new_state["status"] == "candidate"
                       else "reinspection_failed")
            if outcome != "closure_candidate":
                break
        except Exception as exc:  # noqa: BLE001 - one case must not abort peers.
            outcome = "retry_failed"
            rounds.append({"round": round_number,
                           "error": f"{type(exc).__name__}: {exc}"[:500]})
            break
    result = {"item_id": item_id, "status": outcome,
              "rounds": 1 + len(rounds), "details": rounds,
              "terminal": outcome != "retry_failed"}
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def run_iterations(batch: Path, eval_root: Path, work_root: Path,
                   *, max_rounds: int = 3, workers: int = 2) -> dict:
    if not 2 <= max_rounds <= 4 or not 1 <= workers <= 4:
        raise ValueError("invalid_rounds_or_workers")
    cases = json.loads(batch.read_text())["cases"]
    selected = [case for case in cases if (path := eval_root / "cases" /
                case["request"]["item_id"] / "result.json").is_file()
                and json.loads(path.read_text())["status"] == "closure_candidate"]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_iterate, case, eval_root, work_root, max_rounds,
                               os.environ["DASHSCOPE_API_KEY"],
                               os.environ["DASHSCOPE_TTS_ENDPOINT"])
                   for case in selected]
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            results.append(row)
            print(f"pb2_iterate {len(results)}/{len(selected)} "
                  f"{row['item_id']} {row['status']}", flush=True)
    summary = {"schema_version": "dev-pb2.iteration-eval.v1",
               "approval_mode": "simulated_model_proposal",
               "eligible": len(selected),
               "counts": dict(Counter(row["status"] for row in results)),
               "results": sorted(results, key=lambda row: row["item_id"])}
    (eval_root / "iteration-summary.json").write_text(json.dumps(
        summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry surfaced issues after first repair")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--eval-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    result = run_iterations(args.batch, args.eval_root, args.work_root,
                            max_rounds=args.max_rounds, workers=args.workers)
    print(json.dumps({key: result[key] for key in ("eligible", "counts")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
