"""Evidence-only source and ASR review using DeepSeek Flash."""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import os
import re
import time
import urllib.error
import urllib.request
import warnings
from difflib import SequenceMatcher
from pathlib import Path

from .manifest import load_manifest
from .source_patterns import (
    function_value_misphrasing,
    missing_perpendicular_object,
    missing_set_label,
)
from .text_normalization import comparison_text

ENDPOINT = "https://api.deepseek.com/anthropic/v1/messages"
MODEL = "deepseek-flash"

SOURCE_SYSTEM = """你是数学教学视频的旁白内容审查员。只报告原始旁白文本里有直接证据的明显错误。
重点：缺了必须说出的字母/变量/运算对象，造成病句或表达失义；减与负、指数与单位等关键数学含义写错；直接留下无法自然朗读的 TeX。
不要要求旁白逐字念出板书、图形或题干的每一个对象。解释性省略、概括和自然转述都不算缺字；不能仅凭屏幕出现某符号就报错。
问题原文只是辅助判断上下文，不得凭想象补出原文没有的条件。只保留高置信度、员工值得核查的候选。
仅返回 JSON：{"issues":[{"category":"source_missing_object|source_wrong_expression|source_literal_tex","line":整数,"source_quote":"旁白中的连续原文片段","why":"具体缺失或误义","suggested_reading":"修正后的自然口播","confidence":"high|medium"}]}。无问题返回 {"issues":[]}。"""

AUDIO_SYSTEM = """你是数学教学视频的听读差异审查员。输入有最终源码旁白与 Qwen ASR 转写；ASR 本身可能漏字、润色或写错同音字。
只找成片实际读法可能偏离原始旁白的高价值候选：字母/变量、减与负、数字、指数、单位、公式中的关键对象。不要把标点、空格、大小写、中文数字与阿拉伯数字、同义转述当作问题。
只报告 ASR 相对原始旁白少读或读成另一对象的情形；若原始旁白已经缺字而 ASR 反而补出了对象，不要报告。原始旁白缺陷留给源码审查。ASR 差异只是核听候选，不能宣称已证实 TTS 错。
每条必须引用两侧连续原文，ASR 引文必须出现在提供的转写中；提供对应转写片段编号。宁可漏报，不要虚构字词。
仅返回 JSON：{"issues":[{"category":"audio_missing_object|audio_wrong_operator|audio_wrong_number|audio_wrong_unit|audio_wrong_letter|audio_other","source_quote":"源码旁白原文","asr_quote":"ASR 连续原文","segment_index":整数,"why":"为何值得核听","confidence":"high|medium"}]}。无问题返回 {"issues":[]}。"""


def voiceovers(source: str) -> list[dict]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source)
    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "voiceover":
            continue
        for keyword in node.keywords:
            if (keyword.arg == "text" and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str) and keyword.value.value.strip()):
                rows.append({"line": node.lineno, "text": keyword.value.value.strip()})
    return sorted(rows, key=lambda row: row["line"])


def _context(content: object) -> dict:
    if isinstance(content, str):
        content = json.loads(content)
    if not isinstance(content, dict):
        return {}
    return {key: str(content.get(key) or "")[:5000]
            for key in ("question", "problem_text", "solution_steps", "final_answer")
            if content.get(key)}


def _model_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("deepseek_response_has_no_json")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict) or not isinstance(value.get("issues"), list):
        raise TypeError("deepseek_response_missing_issues")
    return value


def _request(system: str, data: dict, key: str) -> tuple[dict, dict]:
    payload = {"model": MODEL, "max_tokens": 2200, "temperature": 0,
               "thinking": {"type": "disabled"}, "system": system,
               "messages": [{"role": "user", "content": json.dumps(data, ensure_ascii=False)}]}
    for attempt in range(4):
        payload["max_tokens"] = 2200 if attempt == 0 else 4000
        request = urllib.request.Request(
            ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST", headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                    "content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
            text = "".join(row.get("text", "") for row in result.get("content") or []
                           if row.get("type") == "text")
            return _model_json(text), result.get("usage") or {}
        except (ValueError, TypeError) as exc:
            if attempt == 3:
                raise RuntimeError("deepseek_invalid_json_after_retries") from exc
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"deepseek_http_{exc.code}:{exc.read(200).decode(errors='replace')}") from exc
        except (TimeoutError, urllib.error.URLError):
            if attempt == 3:
                raise
        time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("deepseek_retry_exhausted")


def _match(quote: object, text: str) -> bool:
    compact = lambda value: re.sub(r"\s+", "", str(value or "")).lower()
    return len(compact(quote)) >= 2 and compact(quote) in compact(text)


def actionable_source_issue(issue: dict) -> bool:
    reason = str(issue.get("why") or "")
    if issue.get("confidence") == "low":
        return False
    if re.search(r"不构成(?:缺陷|问题|错误)|无直接错误|本身正确|无错误|无误|"
                 r"故不报|无法高置信|表述可通|数学上等价", reason):
        return False
    suggested = re.sub(r"\s+", "", str(issue.get("suggested_reading") or ""))
    original = re.sub(r"\s+", "", str(issue.get("source_quote") or ""))
    return not (issue.get("category") == "source_wrong_expression"
                and suggested and suggested == original)


def _spoken_canonical(value: object) -> str:
    text = str(value or "").lower().translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    for old, new in (("下标零", "0"), ("下标一", "1"), ("下标二", "2"),
                     ("负一", "负1"), ("负二", "负2"), ("负三", "负3")):
        text = text.replace(old, new)
    return comparison_text(text)


def _asr_adds_only(source: object, actual: object) -> bool:
    left, right = _spoken_canonical(source), _spoken_canonical(actual)
    edits = [tag for tag, *_ in SequenceMatcher(None, left, right).get_opcodes()
             if tag != "equal"]
    return bool(edits) and all(tag == "insert" for tag in edits)


def _validate_source(raw: list, lines: list[dict]) -> tuple[list[dict], int]:
    valid = []
    for issue in raw:
        if not isinstance(issue, dict):
            continue
        line = next((row for row in lines if row["line"] == issue.get("line")), None)
        if line and _match(issue.get("source_quote"), line["text"]):
            valid.append({**issue, "source_text": line["text"]})
    return valid, len(raw) - len(valid)


def _validate_audio(raw: list, lines: list[dict], segments: list[dict]) -> tuple[list[dict], int]:
    source_text = "".join(row["text"] for row in lines)
    valid = []
    for issue in raw:
        if not isinstance(issue, dict) or not _match(issue.get("source_quote"), source_text):
            continue
        index = issue.get("segment_index")
        if not isinstance(index, int) or index < 1 or index > len(segments):
            index = next((i + 1 for i, row in enumerate(segments)
                          if _match(issue.get("asr_quote"), row.get("text", ""))), None)
        if index is None or not _match(issue.get("asr_quote"), segments[index - 1]["text"]):
            continue
        if (_spoken_canonical(issue.get("source_quote"))
                == _spoken_canonical(issue.get("asr_quote"))
                or _asr_adds_only(issue.get("source_quote"), issue.get("asr_quote"))):
            continue
        row = segments[index - 1]
        valid.append({**issue, "segment_index": index,
                      "start_ms": row["start_ms"], "end_ms": row["end_ms"]})
    return valid, len(raw) - len(valid)


def review_one(row: dict, questions: dict, asr_items: dict, source_issues: dict,
               mode: str, key: str) -> dict:
    item_id = row["item_id"]
    lines = voiceovers(Path(row["source_path"]).read_text(encoding="utf-8"))
    if not lines:
        return {"item_id": item_id, "status": "failed_open", "error": "no_voiceovers"}
    if mode == "source":
        data = {"question_context": _context(questions.get(item_id)), "voiceovers": lines}
        system = SOURCE_SYSTEM
    else:
        asr = asr_items.get(item_id) or {}
        if asr.get("status") != "completed":
            return {"item_id": item_id, "status": "failed_open", "error": "asr_unavailable"}
        data = {"voiceovers": lines, "asr_segments": [
            {"index": i + 1, "start_ms": segment["start_ms"],
             "end_ms": segment["end_ms"], "text": segment["text"]}
            for i, segment in enumerate(asr["segments"])]}
        system = AUDIO_SYSTEM
    response, usage = _request(system, data, key)
    issues, discarded = (_validate_source(response["issues"], lines) if mode == "source"
                         else _validate_audio(response["issues"], lines, asr["segments"]))
    if mode == "source":
        existing = {(issue.get("line"), issue.get("source_quote")) for issue in issues}
        patterns = (missing_set_label(lines, _context(questions.get(item_id)))
                    + function_value_misphrasing(lines)
                    + missing_perpendicular_object(lines))
        issues.extend(issue for issue in patterns
                      if (issue["line"], issue["source_quote"]) not in existing)
    source_overlap = 0
    if mode == "audio":
        retained = []
        for issue in issues:
            if any(_match(issue.get("source_quote"), source_issue.get("source_quote", ""))
                   or _match(source_issue.get("source_quote"), issue.get("source_quote", ""))
                   for source_issue in source_issues.get(item_id, [])
                   if actionable_source_issue(source_issue)):
                source_overlap += 1
            else:
                retained.append(issue)
        issues = retained
    return {"item_id": item_id, "status": "completed", "mode": mode,
            "model": MODEL, "issues": issues, "discarded_unverifiable": discarded,
            "discarded_source_overlap": source_overlap,
            "usage": usage}


def run_batch(manifest: Path, output: Path, mode: str, key: str,
              questions_path: Path | None = None, asr_dir: Path | None = None,
              source_review_dir: Path | None = None, workers: int = 3,
              limit: int | None = None) -> dict:
    rows = load_manifest(manifest)
    if limit is not None:
        rows = rows[:limit]
    questions = json.loads(questions_path.read_text()) if questions_path else {}
    asr_items = {}
    if mode == "audio" and asr_dir:
        for path in (asr_dir / "items").glob("*.json"):
            result = json.loads(path.read_text())
            asr_items[result["item_id"]] = result
    source_issues = {}
    if mode == "audio" and source_review_dir:
        for path in (source_review_dir / "items").glob("*.json"):
            result = json.loads(path.read_text())
            source_issues[result["item_id"]] = result.get("issues") or []
    output.mkdir(parents=True, exist_ok=True)
    items_dir = output / "items"
    items_dir.mkdir(exist_ok=True)

    def one(row: dict) -> dict:
        target = items_dir / f"{row['item_id']}.json"
        if target.exists():
            previous = json.loads(target.read_text())
            if previous.get("status") == "completed":
                return previous
        try:
            result = review_one(row, questions, asr_items, source_issues, mode, key)
        except Exception as exc:  # noqa: BLE001 - retain each model failure as evidence.
            result = {"item_id": row["item_id"], "status": "failed_open",
                      "error": f"{type(exc).__name__}: {exc}"[:500]}
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        temp.replace(target)
        return result

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for future in concurrent.futures.as_completed([pool.submit(one, row) for row in rows]):
            results.append(future.result())
            if len(results) % 10 == 0 or len(results) == len(rows):
                print(f"semantic_{mode} {len(results)}/{len(rows)} issues="
                      f"{sum(len(row.get('issues') or []) for row in results)} failed="
                      f"{sum(row['status'] != 'completed' for row in results)}", flush=True)
    summary = {"mode": mode, "total": len(rows),
               "completed": sum(row["status"] == "completed" for row in results),
               "failed_open": sum(row["status"] != "completed" for row in results),
               "issue_count": sum(len(row.get("issues") or []) for row in results),
               "candidate_videos": sum(bool(row.get("issues")) for row in results)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepSeek evidence-only semantic screening")
    parser.add_argument("mode", choices=("source", "audio"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--asr-dir", type=Path)
    parser.add_argument("--source-review-dir", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    key = os.environ["DEEPSEEK_API_KEY"]
    print(json.dumps(run_batch(args.manifest, args.output, args.mode, key, args.questions,
                               args.asr_dir, args.source_review_dir, args.workers,
                               args.limit), ensure_ascii=False))


if __name__ == "__main__":
    main()
