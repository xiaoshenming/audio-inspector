"""Deterministic human decisions and repair commands for the BatchOps adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .semantic_review import voiceovers


def _replacement(source: Path, issue: dict, new_text: str) -> dict:
    lines = voiceovers(source.read_text(encoding="utf-8"))
    original = issue["original_text"]
    candidates = [line for line in lines if original in line["text"]
                  and (issue.get("source_line") is None
                       or issue["source_line"] == line["line"])]
    if len(candidates) != 1 or candidates[0]["text"].count(original) != 1:
        raise ValueError("voiceover_target_not_unique")
    line = candidates[0]
    return {"source_line": line["line"], "old_voiceover": line["text"],
            "new_voiceover": line["text"].replace(original, new_text, 1),
            "mode": issue["repair_mode"], "issue_id": issue["issue_id"]}


def decide(inspection: dict, source_path: Path, actor: str, action: str,
           edits: list[dict] | None = None, note: str = "") -> dict:
    if inspection.get("schema_version") != "dev-pb2.inspection.v1":
        raise ValueError("unsupported_inspection_schema")
    if inspection["status"] == "failed_open":
        raise ValueError("incomplete_inspection_requires_manual_investigation")
    if not actor.strip():
        raise ValueError("actor_required")
    source = source_path.resolve()
    actual_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual_sha != inspection["source_sha256"]:
        raise ValueError("stale_source_revision")
    if action == "accept_as_is":
        if edits:
            raise ValueError("accept_as_is_has_no_edits")
        changes: list[dict] = []
        next_action = "continue_delivery"
    elif action == "approve_repair":
        if inspection["status"] != "candidate" or not edits:
            raise ValueError("repair_requires_candidates_and_edits")
        known = {issue["issue_id"]: issue for issue in inspection["issues"]}
        seen: set[str] = set()
        by_line: dict[int, dict] = {}
        for edit in edits:
            issue_id = str(edit.get("issue_id") or "")
            if issue_id not in known or issue_id in seen:
                raise ValueError("unknown_or_duplicate_issue")
            seen.add(issue_id)
            proposed = str(edit.get("new_text") or known[issue_id]["proposed_text"]).strip()
            if not proposed or len(proposed) > 2000:
                raise ValueError("new_text_required")
            change = _replacement(source, known[issue_id], proposed)
            line = change["source_line"]
            if line in by_line:
                current = by_line[line]
                original = known[issue_id]["original_text"]
                if current["new_voiceover"].count(original) != 1:
                    raise ValueError("overlapping_voiceover_edits")
                current["new_voiceover"] = current["new_voiceover"].replace(
                    original, proposed, 1)
                current["issue_ids"].append(issue_id)
                if change["mode"] == "replace_voiceover_text":
                    current["mode"] = change["mode"]
            else:
                change["issue_ids"] = [issue_id]
                by_line[line] = change
        changes = list(by_line.values())
        next_action = "rebuild_final_video"
    else:
        raise ValueError("unknown_action")
    command = {"schema_version": "dev-pb2.decision.v1",
               "item_id": inspection["item_id"],
               "revision_id": inspection["revision_id"],
               "video_sha256": inspection["video_sha256"],
               "source_sha256": inspection["source_sha256"],
               "actor": actor.strip(), "action": action, "note": note[:2000],
               "next_action": next_action, "voiceover_overrides": changes}
    command["idempotency_key"] = hashlib.sha256(json.dumps(command,
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return command
