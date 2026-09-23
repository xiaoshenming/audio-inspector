"""Run the revised module over every previously machine-clean repaired video."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from collections import Counter
from pathlib import Path

from dev_pb2.pipeline import run


def rescreen(requests: Path, work_root: Path, output: Path, workers: int = 2) -> dict:
    paths = sorted(requests.glob("*.json"))
    output.mkdir(parents=True, exist_ok=True)
    results = []

    def one(path: Path) -> dict:
        target = output / path.name
        if target.is_file():
            previous = json.loads(target.read_text())
            if previous.get("status") in {"clean", "candidate"}:
                return previous
        result = run(json.loads(path.read_text()), work_root)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for future in concurrent.futures.as_completed([pool.submit(one, path) for path in paths]):
            result = future.result()
            results.append(result)
            print(f"revised_rescreen {len(results)}/{len(paths)} "
                  f"{result['item_id']} {result['status']}", flush=True)
    counts = Counter(row["status"] for row in results)
    summary = {"videos": len(paths), "counts": dict(counts),
               "new_candidate_videos": [row["item_id"] for row in results
                                        if row["status"] == "candidate"],
               "failed_open_videos": [row["item_id"] for row in results
                                      if row["status"] == "failed_open"]}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False,
                                             indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(rescreen(args.requests, args.work_root, args.output,
                                args.workers), ensure_ascii=False))


if __name__ == "__main__":
    main()
