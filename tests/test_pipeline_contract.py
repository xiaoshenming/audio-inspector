import hashlib
import json

import pytest

from dev_pb2 import pipeline
from dev_pb2.decisions import decide
from dev_pb2.pipeline import prepare, publish


def _dataset(tmp_path, source_issues=None, audio_issues=None, failed_lane=None):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"sample-video")
    source = tmp_path / "scene.py"
    source.write_text('self.voiceover(text="求的值。")\n', encoding="utf-8")
    root = prepare({"item_id": "item-1", "revision_id": "rev-1",
                    "video_path": str(video), "source_path": str(source)}, tmp_path / "work")
    for lane in ("asr-qwen", "semantic-source", "semantic-audio",
                 "literal-asr-targeted", "literal-reading"):
        folder = root / lane / "items"
        folder.mkdir(parents=True)
        issues = (source_issues if lane == "semantic-source" else
                  audio_issues if lane == "semantic-audio" else [])
        (folder / "one.json").write_text(json.dumps({"item_id": "item-1",
            "status": "failed_open" if lane == failed_lane else "completed",
            "issues": issues or []}, ensure_ascii=False))
    return root, source


def test_clean_result_allows_normal_delivery(tmp_path):
    root, _ = _dataset(tmp_path)
    result = publish(root)
    assert result["status"] == "clean"
    assert result["can_continue"] is True
    assert result["unattended_release_validated"] is False
    assert result["issues"] == []


def test_failed_stage_is_never_clean(tmp_path):
    root, source = _dataset(tmp_path, failed_lane="asr-qwen")
    result = publish(root)
    assert result["status"] == "failed_open"
    assert result["can_continue"] is False
    with pytest.raises(ValueError, match="incomplete_inspection"):
        decide(result, source, "reviewer", "accept_as_is")


def test_admin_can_edit_source_proposal_before_rebuild(tmp_path):
    issue = {"category": "source_missing_object", "source_quote": "求的值",
             "suggested_reading": "求 a 的值", "why": "缺少 a", "line": 1,
             "confidence": "high"}
    root, source = _dataset(tmp_path, source_issues=[issue])
    result = publish(root)
    assert result["status"] == "candidate"
    assert result["can_continue"] is False
    proposal = result["issues"][0]
    assert proposal["original_text"] == "求的值"
    assert proposal["proposed_text"] == "求 a 的值"
    command = decide(result, source, "admin-1", "approve_repair",
                     [{"issue_id": proposal["issue_id"], "new_text": "求 b 的值"}])
    assert command["next_action"] == "rebuild_final_video"
    assert command["voiceover_overrides"][0]["new_voiceover"] == "求 b 的值。"
    assert command["revision_id"] == "rev-1"
    assert len(command["idempotency_key"]) == 64
    accepted = decide(result, source, "admin-1", "accept_as_is")
    assert accepted["next_action"] == "continue_delivery"


def test_stale_source_and_unknown_issue_rejected(tmp_path):
    issue = {"category": "source_missing_object", "source_quote": "求的值",
             "suggested_reading": "求 a 的值", "why": "缺少 a", "line": 1}
    root, source = _dataset(tmp_path, source_issues=[issue])
    result = publish(root)
    with pytest.raises(ValueError, match="unknown_or_duplicate_issue"):
        decide(result, source, "admin", "approve_repair", [{"issue_id": "wrong"}])
    source.write_text('self.voiceover(text="改过的旁白")\n')
    assert hashlib.sha256(source.read_bytes()).hexdigest() != result["source_sha256"]
    with pytest.raises(ValueError, match="stale_source_revision"):
        decide(result, source, "admin", "accept_as_is")


def test_audio_issue_resynthesizes_without_inventing_source_edit(tmp_path):
    issue = {"category": "audio_wrong_number", "source_quote": "求的值",
             "asr_quote": "求二的值", "why": "数字不同", "confidence": "medium",
             "start_ms": 2000}
    root, source = _dataset(tmp_path, audio_issues=[issue])
    result = publish(root)
    assert result["status"] == "candidate"
    proposal = result["issues"][0]
    assert proposal["repair_mode"] == "resynthesize_audio"
    assert proposal["proposed_text"] == "求的值"
    assert "同文配音" in proposal["repair_guidance"]
    command = decide(result, source, "admin", "approve_repair",
                     [{"issue_id": proposal["issue_id"]}])
    assert command["voiceover_overrides"][0]["old_voiceover"] == \
        command["voiceover_overrides"][0]["new_voiceover"]
    assert command["voiceover_overrides"][0]["repair_intent"] == "retry_same_text_tts"


def test_changed_subtitle_changes_cache_key_and_inspection_identity(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    source = tmp_path / "source.py"
    source.write_text('self.voiceover(text="你好")\n')
    subtitle = tmp_path / "video.srt"
    subtitle.write_text("first")
    request = {"item_id": "one", "revision_id": "r1", "video_path": str(video),
               "source_path": str(source), "subtitle_path": str(subtitle)}
    first = prepare(request, tmp_path / "work")
    first_sha = publish(first)["subtitle_sha256"]
    subtitle.write_text("second")
    second = prepare(request, tmp_path / "work")
    second_sha = publish(second)["subtitle_sha256"]
    assert first != second
    assert first_sha != second_sha


def test_stale_completed_item_does_not_mask_runner_failure(tmp_path):
    root, _ = _dataset(tmp_path)
    error = root / "semantic-source/items/runner-error.json"
    error.write_text(json.dumps({"item_id": "item-1", "status": "failed_open"}))
    assert publish(root)["status"] == "failed_open"


def test_stage_exception_overrides_cached_completed_item(tmp_path, monkeypatch):
    root, _ = _dataset(tmp_path)
    row = json.loads((root / "metadata/input.json").read_text())
    request = {"item_id": "item-1", "revision_id": "rev-1",
               "video_path": row["video_path"], "source_path": row["source_path"]}

    def unavailable(*args, **kwargs):
        raise RuntimeError("provider_unavailable")

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test")
    monkeypatch.setenv("DASHSCOPE_ASR_ENDPOINT", "test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setattr(pipeline.qwen_asr, "run_batch", unavailable)
    monkeypatch.setattr(pipeline.semantic_review, "run_batch", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.literal_asr, "run_batch", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.literal_reading, "run_batch", lambda *args, **kwargs: None)
    assert pipeline.run(request, tmp_path / "work")["status"] == "failed_open"


def test_runner_exception_publishes_failed_open(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    source = tmp_path / "source.py"
    source.write_text('self.voiceover(text="你好")\n')

    def unavailable(*args, **kwargs):
        raise RuntimeError("provider_unavailable")

    for component in (pipeline.qwen_asr, pipeline.semantic_review,
                      pipeline.literal_asr, pipeline.literal_reading):
        monkeypatch.setattr(component, "run_batch", unavailable)
    result = pipeline.run({"item_id": "x", "revision_id": "r1",
                           "video_path": str(video), "source_path": str(source)},
                          tmp_path / "run")
    assert result["status"] == "failed_open"
    assert result["can_continue"] is False
    assert set(result["lanes"].values()) == {"failed_open"}
