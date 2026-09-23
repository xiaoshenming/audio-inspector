"""Deterministic human decisions and repair commands for the BatchOps adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .literal_phrasing import rewrite_function_notation
from .semantic_review import voiceovers


def _replacement(source: Path, issue: dict, new_text: str) -> dict:
    lines = voiceovers(source.read_text(encoding="utf-8"))
    original = issue["original_text"]
    candidates = [line for line in lines if original in line["text"]
                  and (issue.get("source_line") is None
                       or issue["source_line"] == line["line"])]
    if len(candidates) != 1 or candidates[0]["text"].count(original) != 1:
        raise ValueError("voiceover_target_not_unique")
    if new_text == original and issue["repair_mode"] != "resynthesize_audio":
        raise ValueError("source_repair_requires_changed_text")
    line = candidates[0]
    return {"source_line": line["line"], "old_voiceover": line["text"],
            "new_voiceover": line["text"].replace(original, new_text, 1),
            "mode": ("replace_voiceover_text" if new_text != original
                     else issue["repair_mode"]), "issue_id": issue["issue_id"],
            "repair_intent": ("retry_same_text_tts" if new_text == original
                              and issue["repair_mode"] == "resynthesize_audio"
                              else "change_spoken_text")}


def _manual_replacement(source: Path, edit: dict) -> dict:
    """Let an administrator correct a line the screening model did not flag."""
    old = str(edit.get("old_voiceover") or "")
    new = str(edit.get("new_voiceover") or "").strip()
    line_number = edit.get("source_line")
    if not old or not new or len(new) > 2000 or old == new:
        raise ValueError("manual_voiceover_requires_distinct_old_and_new_text")
    lines = voiceovers(source.read_text(encoding="utf-8"))
    matches = [line for line in lines if line["text"] == old
               and (line_number is None or line["line"] == line_number)]
    if len(matches) != 1:
        raise ValueError("manual_voiceover_target_not_unique")
    return {"source_line": matches[0]["line"], "old_voiceover": old,
            "new_voiceover": new, "mode": "replace_voiceover_text",
            "repair_intent": "change_spoken_text", "issue_ids": []}


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
        if not edits:
            raise ValueError("repair_requires_edits")
        known = {issue["issue_id"]: issue for issue in inspection["issues"]}
        seen: set[str] = set()
        by_line: dict[int, dict] = {}
        for edit in edits:
            if "old_voiceover" in edit:
                change = _manual_replacement(source, edit)
                if change["source_line"] in by_line:
                    raise ValueError("overlapping_voiceover_edits")
                by_line[change["source_line"]] = change
                continue
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
                if (known[issue_id]["category"] == "audio_literal_formula"
                        and original == current["old_voiceover"]
                        and proposed == rewrite_function_notation(original)):
                    current["new_voiceover"] = rewrite_function_notation(
                        current["new_voiceover"])
                else:
                    if current["new_voiceover"].count(original) != 1:
                        raise ValueError("overlapping_voiceover_edits")
                    current["new_voiceover"] = current["new_voiceover"].replace(
                        original, proposed, 1)
                current["issue_ids"].append(issue_id)
                if change["mode"] == "replace_voiceover_text":
                    current["mode"] = change["mode"]
                if current["new_voiceover"] != current["old_voiceover"]:
                    current["repair_intent"] = "change_spoken_text"
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
               "next_action": next_action, "voiceover_overrides": changes,
               "subtitle_sha256": inspection.get("subtitle_sha256", "")}
    command["idempotency_key"] = hashlib.sha256(json.dumps(command,
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return command
