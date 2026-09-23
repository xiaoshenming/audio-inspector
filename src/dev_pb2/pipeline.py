"""Run the frozen screening lanes and publish one bounded BatchOps handoff result."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

from . import __version__, literal_asr, literal_reading, qwen_asr, screening_report, semantic_review
from .manifest import load_manifest

LANES = ("asr-qwen", "semantic-source", "semantic-audio",
         "literal-asr-targeted", "literal-reading")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(request: dict, work_root: Path) -> Path:
    item_id = str(request.get("item_id") or "").strip()
    revision_id = str(request.get("revision_id") or "").strip()
    if not item_id or not revision_id:
        raise ValueError("item_id_and_revision_id_required")
    video = Path(str(request.get("video_path") or "")).expanduser().resolve()
    source = Path(str(request.get("source_path") or "")).expanduser().resolve()
    if not video.is_file() or not source.is_file():
        raise ValueError("video_and_source_files_required")
    subtitle = str(request.get("subtitle_path") or "")
    if subtitle and not Path(subtitle).is_file():
        raise ValueError("subtitle_file_missing")
    hashes = {"video_sha256": _sha(video), "source_sha256": _sha(source),
              "subtitle_sha256": _sha(Path(subtitle)) if subtitle else ""}
    for name, digest in hashes.items():
        if request.get(name) and request[name] != digest:
            raise ValueError(f"{name}_mismatch")
    key = hashlib.sha256(json.dumps([item_id, revision_id, hashes,
                                    request.get("question"), __version__],
                                    sort_keys=True).encode()).hexdigest()[:24]
    root = work_root / key
    metadata = root / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    row = {"item_id": item_id, "video_path": str(video), "source_path": str(source),
           "subtitle_path": subtitle}
    (root / "manifest.json").write_text(json.dumps({"items": [row]}, ensure_ascii=False,
                                                indent=2) + "\n", encoding="utf-8")
    with (metadata / "samples.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["item_id", "external_key", "batch_name",
                                                  "tts_status", "duration_seconds",
                                                  "subtitle_path"])
        writer.writeheader()
        writer.writerow({"item_id": item_id,
                         "external_key": str(request.get("external_key") or item_id),
                         "batch_name": str(request.get("batch_name") or ""),
                         "tts_status": "succeeded", "duration_seconds": "0",
                         "subtitle_path": subtitle})
    (metadata / "questions.json").write_text(json.dumps({item_id: request.get("question") or {}},
                                                      ensure_ascii=False) + "\n")
    (metadata / "input.json").write_text(json.dumps({**row, **hashes,
        "revision_id": revision_id}, ensure_ascii=False, indent=2) + "\n")
    return root


def _item_status(directory: Path, item_id: str) -> str:
    error_file = directory / "items/runner-error.json"
    if error_file.is_file():
        error = json.loads(error_file.read_text())
        if error.get("item_id") == item_id:
            return "failed_open"
    statuses = []
    for path in (directory / "items").glob("*.json"):
        value = json.loads(path.read_text())
        if value.get("item_id") == item_id:
            statuses.append(str(value.get("status") or "missing"))
    return statuses[0] if len(statuses) == 1 else "missing"


def publish(root: Path) -> dict:
    rows = load_manifest(root / "manifest.json")
    if len(rows) != 1:
        raise ValueError("one_item_per_inspection_required")
    item_id = rows[0]["item_id"]
    identity = json.loads((root / "metadata/input.json").read_text())
    lane_status = {name: _item_status(root / name, item_id) for name in LANES}
    complete = all(status == "completed" for status in lane_status.values())
    candidates = screening_report.compile_candidates(root) if complete else []
    issues = []
    for candidate in candidates:
        for issue in candidate["source_issues"] + candidate["audio_issues"]:
            source_text = str(issue.get("source_quote") or "")
            observed = str(issue.get("asr_quote") or "")
            kind = issue["kind"]
            proposal = (str(issue.get("suggested_reading") or "") if kind == "source"
                        else source_text)
            issue_id = hashlib.sha256(json.dumps([item_id, kind, issue.get("category"),
                issue.get("line"), source_text, observed], ensure_ascii=False).encode()).hexdigest()[:20]
            issues.append({"issue_id": issue_id, "kind": kind,
                           "category": issue.get("category"),
                           "priority": candidate["priority"],
                           "time_seconds": issue.get("time_seconds"),
                           "source_line": issue.get("line"),
                           "original_text": source_text,
                           "observed_text": observed,
                           "proposed_text": proposal,
                           "repair_mode": ("replace_voiceover_text" if kind == "source"
                                           else "resynthesize_audio"),
                           "repair_guidance": ("核对并编辑建议口播，再重新配音" if kind == "source"
                                               else "原文未改；仅重试同文配音。若读法有歧义，"
                                                    "请在输入框写出明确的新口播。"),
                           "reason": issue.get("why", "")})
    status = "failed_open" if not complete else "candidate" if issues else "clean"
    result = {"schema_version": "dev-pb2.inspection.v1", "item_id": item_id,
              "revision_id": identity["revision_id"],
              "video_sha256": identity["video_sha256"],
              "source_sha256": identity["source_sha256"],
              "subtitle_sha256": identity["subtitle_sha256"],
              "status": status, "lanes": lane_status, "issues": issues,
              "can_continue": status == "clean", "needs_admin_review": status != "clean",
              "evidence_only": True, "unattended_release_validated": False}
    (root / "inspection.json").write_text(json.dumps(result, ensure_ascii=False,
                                                      indent=2) + "\n")
    return result


def run(request: dict, work_root: Path) -> dict:
    root = prepare(request, work_root)
    manifest = root / "manifest.json"
    item_id = json.loads(manifest.read_text())["items"][0]["item_id"]

    def stage(name: str, function) -> None:
        error_file = root / name / "items/runner-error.json"
        try:
            function()
            error_file.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - publish failed_open evidence.
            error_file.parent.mkdir(parents=True, exist_ok=True)
            error_file.write_text(json.dumps({
                "item_id": item_id, "status": "failed_open",
                "error": f"{type(exc).__name__}: {exc}"[:300]}, ensure_ascii=False) + "\n")

    stage("asr-qwen", lambda: qwen_asr.run_batch(
        manifest, root / "asr-qwen", os.environ["DASHSCOPE_API_KEY"],
        os.environ["DASHSCOPE_ASR_ENDPOINT"]))
    stage("semantic-source", lambda: semantic_review.run_batch(
        manifest, root / "semantic-source", "source", os.environ["DEEPSEEK_API_KEY"],
        root / "metadata/questions.json"))
    stage("semantic-audio", lambda: semantic_review.run_batch(
        manifest, root / "semantic-audio", "audio", os.environ["DEEPSEEK_API_KEY"],
        asr_dir=root / "asr-qwen", source_review_dir=root / "semantic-source"))
    stage("literal-asr-targeted", lambda: literal_asr.run_batch(
        manifest, root / "literal-asr-targeted",
        model_name=os.environ.get("DEV_PB2_WHISPER_MODEL", "small"),
        targeted=True, max_clips=0))
    stage("literal-reading", lambda: literal_reading.run_batch(
        manifest, root / "literal-asr-targeted", root / "literal-reading"))
    return publish(root)
