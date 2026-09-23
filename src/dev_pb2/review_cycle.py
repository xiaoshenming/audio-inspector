"""Persistent inspect → admin decision → revoice → inspect review cycle."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .decisions import decide
from .pipeline import run
from .repair_media import rebuild, validate_tts_profile
from .review_resources import digest, snapshot, verify
from .source_revision import revise_pack
from .worker_render import _profiles, render_and_inspect


def _write(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".cycle-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def _locked(session: Path):
    session.mkdir(parents=True, exist_ok=True, mode=0o700)
    session.chmod(0o700)
    with (session / "cycle.lock").open("a+b") as lock:
        os.fchmod(lock.fileno(), 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("session_busy") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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
            "pending_decision": state.get("pending_decision"),
            "last_error": state.get("last_error"),
            "decision_count": len(state["history"])}


def _media_matches(state: dict) -> None:
    verify(state)


def start(request: dict, *, session: Path, work_root: Path,
          unburned: Path | None = None, source_pack: Path | None = None,
          repair_mode: str = "local") -> dict:
    if repair_mode not in {"local", "worker"}:
        raise ValueError("unsupported_repair_mode")
    if repair_mode == "worker":
        _profiles(request)
    elif unburned or source_pack:
        validate_tts_profile(request.get("tts_profile"))
    with _locked(session):
        return _start_locked(request, session=session, work_root=work_root,
                             unburned=unburned, source_pack=source_pack,
                             repair_mode=repair_mode)


def _start_locked(request: dict, *, session: Path, work_root: Path,
                  unburned: Path | None, source_pack: Path | None,
                  repair_mode: str) -> dict:
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
             "history": [], "release": release,
             "pending_decision": None, "last_error": None}
    state["resource_sha256"] = snapshot(state)
    _media_matches(state)
    _write(session / "cycle.json", state)
    return state


def retry_inspection(session: Path) -> dict:
    with _locked(session):
        return _retry_inspection_locked(session)


def _retry_inspection_locked(session: Path) -> dict:
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
    with _locked(session):
        return _apply_locked(session, actor=actor, action=action, edits=edits,
                             note=note, api_key=api_key, tts_endpoint=tts_endpoint)


def _apply_locked(session: Path, *, actor: str, action: str,
                  edits: list[dict] | None, note: str,
                  api_key: str, tts_endpoint: str) -> dict:
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
    if state.get("repair_mode", "local") == "local":
        if not api_key or not tts_endpoint:
            raise ValueError("tts_credentials_required")
        if not state["unburned_path"]:
            raise ValueError("unburned_video_required")
    state["phase"] = "repairing"
    state["pending_decision"] = decision
    state["last_error"] = None
    _write(session / "cycle.json", state)
    return _finish_pending_locked(session, state, api_key=api_key,
                                  tts_endpoint=tts_endpoint)


def resume_repair(session: Path, *, api_key: str = "", tts_endpoint: str = "") -> dict:
    with _locked(session):
        state = load(session)
        if state["phase"] != "repairing" or not state.get("pending_decision"):
            raise ValueError("session_not_repairing")
        _media_matches(state)
        return _finish_pending_locked(session, state, api_key=api_key,
                                      tts_endpoint=tts_endpoint)


def _finish_pending_locked(session: Path, state: dict, *, api_key: str,
                           tts_endpoint: str) -> dict:
    try:
        return _perform_pending_repair(session, state, api_key=api_key,
                                       tts_endpoint=tts_endpoint)
    except Exception as exc:
        state["last_error"] = f"{type(exc).__name__}: {exc}"[:500]
        _write(session / "cycle.json", state)
        raise


def _perform_pending_repair(session: Path, state: dict, *, api_key: str,
                            tts_endpoint: str) -> dict:
    request, inspection = state["request"], state["inspection"]
    decision = state["pending_decision"]
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
        repaired = rebuild(inspection, decision, video=Path(request["video_path"]),
                           unburned=Path(state["unburned_path"]),
                           subtitle=Path(request["subtitle_path"]),
                           source_pack=Path(state["source_pack_path"]), output=output,
                           api_key=api_key, tts_endpoint=tts_endpoint,
                           tts_profile=request.get("tts_profile"))
        next_unburned = str(output / "corrected-unburned.mp4")
        revised = {**request, "revision_id": request["revision_id"]
                   + ":pb2:" + decision["idempotency_key"][:12],
                   "video_path": repaired["video_path"],
                   "video_sha256": repaired["video_sha256"],
                   "source_path": repaired["source_path"],
                   "source_sha256": repaired["source_sha256"],
                   "subtitle_path": repaired["subtitle_path"],
                   "subtitle_sha256": repaired.get("subtitle_sha256") or digest(
                       Path(repaired["subtitle_path"]))}
        after = run(revised, Path(state["work_root"]))
    if state.get("repair_mode", "local") == "worker":
        revised = {**request, "revision_id": after["revision_id"],
                   "video_path": repaired["video_path"],
                   "video_sha256": repaired["video_sha256"],
                   "source_path": repaired["source_path"],
                   "source_sha256": repaired["source_sha256"],
                   "subtitle_path": repaired["subtitle_path"],
                   "subtitle_sha256": (repaired.get("subtitle_sha256") or digest(
                       Path(repaired["subtitle_path"]))) if repaired["subtitle_path"] else ""}
    _media_matches(state)
    completed = copy.deepcopy(state)
    completed["history"].append({"round": state["round"], "inspection": inspection,
                                 "decision": decision, "repair": repaired})
    completed.update({"round": round_number, "request": revised, "inspection": after,
                      "unburned_path": next_unburned,
                      "source_pack_path": repaired["source_pack_path"],
                      "phase": "awaiting_admin" if after["status"] != "failed_open"
                      else "inspection_failed", "release": None,
                      "pending_decision": None, "last_error": None})
    completed["resource_sha256"] = snapshot(completed)
    _media_matches(completed)
    _write(session / "cycle.json", completed)
    return completed


def main() -> None:
    from .review_cycle_cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
