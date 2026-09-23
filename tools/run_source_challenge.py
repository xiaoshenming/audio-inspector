"""Second prompt audit of source omissions in previously unflagged videos."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from collections import Counter
from pathlib import Path

from dev_pb2.semantic_review import _request, _validate_source

SYSTEM = """你是数学教学口播的独立复核员。本批文本先前没有被报错，请专门寻找可能漏掉的明显口播缺陷。
逐句核对题干中明确存在的变量、字母、数字、运算符、指数和单位；特别注意“向量与 b”“求的值”“x 加等于零”等缺对象病句，减与负、平方与立方混淆，以及无法自然朗读的函数记号。
只报告旁白自身确有不完整或数学对象错误、且题干或紧邻上下文能明确确定正确文字的情况。屏幕内容没有逐字念出来不是错误；自然概括、同义说法也不是错误。不要靠猜测补条件。
仅返回 JSON：{"issues":[{"line":整数,"category":"source_missing_object|source_wrong_expression|source_literal_tex","source_quote":"对应口播中的连续原文","suggested_reading":"精简的建议新文","why":"具体证据"}]}。没有问题返回 {"issues":[]}。"""


def run(dataset: Path, output: Path, key: str, workers: int = 3) -> dict:
    rows = json.loads(dataset.read_text())["items"]
    items = output / "items"
    items.mkdir(parents=True, exist_ok=True)

    def one(row: dict) -> dict:
        target = items / f"{row['item_id']}.json"
        if target.is_file():
            previous = json.loads(target.read_text())
            if previous.get("status") == "completed":
                return previous
        try:
            answer, usage = _request(SYSTEM, {"question_context": row["question_context"],
                                               "voiceovers": row["voiceovers"]}, key)
            valid, discarded = _validate_source(answer["issues"], row["voiceovers"])
            result = {"item_id": row["item_id"], "status": "completed",
                      "issues": valid, "discarded_unverifiable": discarded,
                      "usage": usage}
        except Exception as exc:  # noqa: BLE001 - preserve provider failure evidence.
            result = {"item_id": row["item_id"], "status": "failed_open",
                      "error": f"{type(exc).__name__}: {exc}"[:300]}
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return result

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for future in concurrent.futures.as_completed([pool.submit(one, row) for row in rows]):
            results.append(future.result())
            if len(results) % 10 == 0 or len(results) == len(rows):
                print(f"source_challenge {len(results)}/{len(rows)}", flush=True)
    counts = Counter(row["status"] for row in results)
    summary = {"videos": len(rows), "completed": counts["completed"],
               "failed_open": counts["failed_open"],
               "candidate_videos": sum(bool(row.get("issues")) for row in results),
               "issues": sum(len(row.get("issues") or []) for row in results)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False,
                                             indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, args.output,
                         os.environ["DEEPSEEK_API_KEY"], args.workers),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
