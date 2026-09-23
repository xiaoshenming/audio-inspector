"""Persistent inspect → admin decision → revoice → inspect review cycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from .decisions import decide
from .pipeline import run
from .repair_media import rebuild
from .source_revision import revise_pack
from .worker_render import render_and_inspect


def _write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def load(session: Path) -> dict:
    return json.loads((session / "cycle.json").read_text(encoding="utf-8"))


def view(state: dict) -> dict:
    """Small stable response for a caller; full evidence stays in cycle.json."""
    inspection = state["inspection"]
    return {"schema_version": state["schema_version"],
            "item_id": inspection["item_id"], "phase": state["phase"],
            "round": state["round"], "inspection_status": inspection["status"],
            "revision_id": inspection["revision_id"],
            "video_path": state["request"]["video_path"],
            "video_sha256": inspection["video_sha256"],
            "issues": inspection["issues"], "release": state["release"],
            "decision_count": len(state["history"])}


def _media_matches(state: dict) -> None:
    request, inspection = state["request"], state["inspection"]
    for field in ("video", "source"):
        path = Path(request[f"{field}_path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != inspection[
                f"{field}_sha256"]:
            raise ValueError(f"stale_{field}_revision")


def start(request: dict, *, session: Path, work_root: Path,
          unburned: Path | None = None, source_pack: Path | None = None,
          repair_mode: str = "local") -> dict:
    if repair_mode not in {"local", "worker"}:
        raise ValueError("unsupported_repair_mode")
    session.mkdir(parents=True, exist_ok=True)
    if (session / "cycle.json").exists():
        raise ValueError("session_already_exists")
    inspection = run(request, work_root)
    if inspection["status"] == "clean":
        phase = "release_ready"
    elif inspection["status"] == "candidate":
        phase = "awaiting_admin"
    else:
        phase = "inspection_failed"
    release = ({"item_id": inspection["item_id"],
                "revision_id": inspection["revision_id"],
                "video_path": request["video_path"],
                "video_sha256": inspection["video_sha256"],
                "decision_id": None} if phase == "release_ready" else None)
    state = {"schema_version": "dev-pb2.review-cycle.v1", "phase": phase,
             "round": 0, "request": request, "inspection": inspection,
             "work_root": str(work_root), "unburned_path": str(unburned) if unburned else "",
             "source_pack_path": str(source_pack) if source_pack else "",
             "repair_mode": repair_mode,
             "history": [], "release": release}
    _write(session / "cycle.json", state)
    return state


def retry_inspection(session: Path) -> dict:
    state = load(session)
    if state["phase"] != "inspection_failed":
        raise ValueError("session_not_inspection_failed")
    _media_matches(state)
    inspection = run(state["request"], Path(state["work_root"]))
    state["inspection"] = inspection
    if inspection["status"] == "failed_open":
        state["phase"] = "inspection_failed"
    elif state["round"] == 0 and inspection["status"] == "clean":
        state["phase"] = "release_ready"
        state["release"] = {"item_id": inspection["item_id"],
                            "revision_id": inspection["revision_id"],
                            "video_path": state["request"]["video_path"],
                            "video_sha256": inspection["video_sha256"],
                            "decision_id": None}
    else:
        state["phase"] = "awaiting_admin"
    _write(session / "cycle.json", state)
    return state


def apply(session: Path, *, actor: str, action: str,
          edits: list[dict] | None = None, note: str = "",
          api_key: str = "", tts_endpoint: str = "") -> dict:
    state = load(session)
    if state["phase"] != "awaiting_admin":
        raise ValueError("session_not_awaiting_admin")
    _media_matches(state)
    request, inspection = state["request"], state["inspection"]
    decision = decide(inspection, Path(request["source_path"]), actor, action, edits, note)
    if action == "accept_as_is":
        state["history"].append({"round": state["round"], "decision": decision})
        state["phase"] = "release_ready"
        state["release"] = {"item_id": inspection["item_id"],
                            "revision_id": inspection["revision_id"],
                            "video_path": request["video_path"],
                            "video_sha256": inspection["video_sha256"],
                            "decision_id": decision["idempotency_key"]}
        _write(session / "cycle.json", state)
        return state
    if not state["source_pack_path"]:
        raise ValueError("repair_assets_required")
    round_number = state["round"] + 1
    output = session / f"round-{round_number}" / "repaired"
    if state.get("repair_mode", "local") == "worker":
        patched = revise_pack(Path(state["source_pack_path"]),
                              decision["voiceover_overrides"], output / "source")
        closure = render_and_inspect(request, patched.parent / "source.tar", patched,
                                     output / "render", Path(state["work_root"]),
                                     job_item_id=request["item_id"] + "-pb2-"
                                     + decision["idempotency_key"][:12])
        rendered, after = closure["render"], closure["reinspection"]
        repaired = {**rendered, "source_pack_path": str(patched.parent / "source.tar")}
        next_unburned = ""
    else:
        if not api_key or not tts_endpoint:
            raise ValueError("tts_credentials_required")
        if not state["unburned_path"]:
            raise ValueError("unburned_video_required")
        repaired = rebuild(inspection, decision, video=Path(request["video_path"]),
                           unburned=Path(state["unburned_path"]),
                           subtitle=Path(request["subtitle_path"]),
                           source_pack=Path(state["source_pack_path"]), output=output,
                           api_key=api_key, tts_endpoint=tts_endpoint)
        next_unburned = str(output / "corrected-unburned.mp4")
        revised = {**request, "revision_id": request["revision_id"]
                   + ":pb2:" + decision["idempotency_key"][:12],
                   "video_path": repaired["video_path"],
                   "video_sha256": repaired["video_sha256"],
                   "source_path": repaired["source_path"],
                   "source_sha256": repaired["source_sha256"],
                   "subtitle_path": repaired["subtitle_path"]}
        after = run(revised, Path(state["work_root"]))
    if state.get("repair_mode", "local") == "worker":
        revised = {**request, "revision_id": after["revision_id"],
                   "video_path": repaired["video_path"],
                   "video_sha256": repaired["video_sha256"],
                   "source_path": repaired["source_path"],
                   "source_sha256": repaired["source_sha256"],
                   "subtitle_path": repaired["subtitle_path"]}
    state["history"].append({"round": state["round"], "inspection": inspection,
                             "decision": decision, "repair": repaired})
    state.update({"round": round_number, "request": revised, "inspection": after,
                  "unburned_path": next_unburned,
                  "source_pack_path": repaired["source_pack_path"],
                  "phase": "awaiting_admin" if after["status"] != "failed_open"
                  else "inspection_failed", "release": None})
    _write(session / "cycle.json", state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the standalone human TTS review cycle")
    actions = parser.add_subparsers(dest="command", required=True)
    begin = actions.add_parser("start")
    begin.add_argument("--request", type=Path, required=True)
    begin.add_argument("--session", type=Path, required=True)
    begin.add_argument("--work-root", type=Path, required=True)
    begin.add_argument("--unburned", type=Path)
    begin.add_argument("--source-pack", type=Path)
    begin.add_argument("--repair-mode", choices=("local", "worker"), default="local")
    review = actions.add_parser("decide")
    review.add_argument("--session", type=Path, required=True)
    review.add_argument("--actor", required=True)
    review.add_argument("--action", choices=("accept_as_is", "approve_repair"), required=True)
    review.add_argument("--edits", type=Path)
    review.add_argument("--note", default="")
    status = actions.add_parser("status")
    status.add_argument("--session", type=Path, required=True)
    retry = actions.add_parser("retry")
    retry.add_argument("--session", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "start":
        state = start(json.loads(args.request.read_text(encoding="utf-8")),
                      session=args.session, work_root=args.work_root,
                      unburned=args.unburned, source_pack=args.source_pack,
                      repair_mode=args.repair_mode)
    elif args.command == "decide":
        edits = json.loads(args.edits.read_text(encoding="utf-8")) if args.edits else None
        state = apply(args.session, actor=args.actor, action=args.action,
                      edits=edits, note=args.note,
                      api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
                      tts_endpoint=os.environ.get("DASHSCOPE_TTS_ENDPOINT", ""))
    elif args.command == "retry":
        state = retry_inspection(args.session)
    else:
        state = load(args.session)
    print(json.dumps(view(state), ensure_ascii=False))


if __name__ == "__main__":
    main()
