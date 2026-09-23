import hashlib
from pathlib import Path

import pytest

from dev_pb2 import review_cycle


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path, monkeypatch, first="candidate"):
    video = tmp_path / "original.mp4"
    video.write_bytes(b"original video")
    source = tmp_path / "main.py"
    source.write_text('self.voiceover(text="求的值。")\n', encoding="utf-8")
    subtitle = tmp_path / "original.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n求的值。\n")
    unburned = tmp_path / "unburned.mp4"
    unburned.write_bytes(b"unburned")
    pack = tmp_path / "source.tar"
    pack.write_bytes(b"pack")
    request = {"item_id": "one", "revision_id": "r1", "video_path": str(video),
               "source_path": str(source), "subtitle_path": str(subtitle)}

    def inspect(current, _work):
        is_first = current["revision_id"] == "r1"
        status = first if is_first else "clean"
        issues = ([{"issue_id": "i1", "source_line": 1,
                    "original_text": "求的值", "proposed_text": "求 a 的值",
                    "category": "source_missing_object", "repair_mode": "replace_voiceover_text"}]
                  if status == "candidate" else [])
        return {"schema_version": "dev-pb2.inspection.v1", "item_id": "one",
                "revision_id": current["revision_id"], "video_sha256": _sha(Path(current["video_path"])),
                "source_sha256": _sha(Path(current["source_path"])),
                "status": status, "issues": issues}

    calls = []

    def repair(_inspection, decision, **kwargs):
        calls.append(decision)
        output = kwargs["output"]
        output.mkdir(parents=True)
        new_video = output / "final.mp4"
        new_video.write_bytes(b"repaired video")
        new_source = output / "main.py"
        new_source.write_text('self.voiceover(text="求 a 的值。")\n', encoding="utf-8")
        new_srt = output / "corrected.srt"
        new_srt.write_text("repaired")
        (output / "corrected-unburned.mp4").write_bytes(b"new unburned")
        new_pack = output / "source.tar"
        new_pack.write_bytes(b"new pack")
        return {"video_path": str(new_video), "video_sha256": _sha(new_video),
                "source_path": str(new_source), "source_sha256": _sha(new_source),
                "subtitle_path": str(new_srt), "source_pack_path": str(new_pack)}

    monkeypatch.setattr(review_cycle, "run", inspect)
    monkeypatch.setattr(review_cycle, "rebuild", repair)
    return request, unburned, pack, calls


def test_clean_initial_result_is_ready_without_admin(tmp_path, monkeypatch):
    request, unburned, pack, _ = _fixture(tmp_path, monkeypatch, "clean")
    state = review_cycle.start(request, session=tmp_path / "session",
                               work_root=tmp_path / "work", unburned=unburned,
                               source_pack=pack)
    assert state["phase"] == "release_ready"
    assert state["inspection"]["status"] == "clean"
    with pytest.raises(ValueError, match="not_awaiting_admin"):
        review_cycle.apply(tmp_path / "session", actor="admin", action="accept_as_is")


def test_admin_repair_then_second_admin_release(tmp_path, monkeypatch):
    request, unburned, pack, calls = _fixture(tmp_path, monkeypatch)
    session = tmp_path / "session"
    state = review_cycle.start(request, session=session, work_root=tmp_path / "work",
                               unburned=unburned, source_pack=pack)
    assert state["phase"] == "awaiting_admin"
    state = review_cycle.apply(session, actor="admin", action="approve_repair",
                               edits=[{"issue_id": "i1", "new_text": "求 a 的值"}],
                               api_key="test", tts_endpoint="test")
    assert state["phase"] == "awaiting_admin"
    assert state["round"] == 1
    assert state["inspection"]["status"] == "clean"
    assert calls[0]["voiceover_overrides"][0]["new_voiceover"] == "求 a 的值。"
    assert state["release"] is None
    state = review_cycle.apply(session, actor="admin", action="accept_as_is")
    assert state["phase"] == "release_ready"
    assert state["release"]["video_sha256"] == _sha(Path(state["request"]["video_path"]))
    assert len(calls) == 1


def test_admin_can_repair_clean_reinspection_again(tmp_path, monkeypatch):
    request, unburned, pack, calls = _fixture(tmp_path, monkeypatch)
    session = tmp_path / "session"
    review_cycle.start(request, session=session, work_root=tmp_path / "work",
                       unburned=unburned, source_pack=pack)
    review_cycle.apply(session, actor="admin", action="approve_repair",
                       edits=[{"issue_id": "i1"}], api_key="test", tts_endpoint="test")
    state = review_cycle.apply(session, actor="admin", action="approve_repair",
                               edits=[{"source_line": 1, "old_voiceover": "求 a 的值。",
                                       "new_voiceover": "求 b 的值。"}],
                               api_key="test", tts_endpoint="test")
    assert state["round"] == 2
    assert state["phase"] == "awaiting_admin"
    assert len(calls) == 2


def test_stale_media_cannot_be_released(tmp_path, monkeypatch):
    request, unburned, pack, _ = _fixture(tmp_path, monkeypatch)
    session = tmp_path / "session"
    review_cycle.start(request, session=session, work_root=tmp_path / "work",
                       unburned=unburned, source_pack=pack)
    Path(request["video_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="stale_video_revision"):
        review_cycle.apply(session, actor="admin", action="accept_as_is")


def test_worker_route_returns_to_admin_with_new_revision(tmp_path, monkeypatch):
    request, unburned, pack, _ = _fixture(tmp_path, monkeypatch)
    session = tmp_path / "session"

    def patched(_pack, overrides, output):
        assert overrides[0]["new_voiceover"] == "求 a 的值。"
        output.mkdir(parents=True)
        (output / "source.tar").write_bytes(b"revised pack")
        main = output / "main.py"
        main.write_text('self.voiceover(text="求 a 的值。")\n', encoding="utf-8")
        return main

    def rendered(current, _pack, main, output, _work, job_item_id=None):
        assert job_item_id.startswith("one-pb2-")
        output.mkdir(parents=True)
        video = output / "final.mp4"
        video.write_bytes(b"worker video")
        subtitle = output / "final.srt"
        subtitle.write_text("repaired")
        revised = {**current, "revision_id": "r2", "video_path": str(video),
                   "source_path": str(main), "subtitle_path": str(subtitle)}
        return {"render": {"video_path": str(video), "video_sha256": _sha(video),
                           "source_path": str(main), "source_sha256": _sha(main),
                           "subtitle_path": str(subtitle)},
                "reinspection": review_cycle.run(revised, tmp_path / "work")}

    monkeypatch.setattr(review_cycle, "revise_pack", patched)
    monkeypatch.setattr(review_cycle, "render_and_inspect", rendered)
    review_cycle.start(request, session=session, work_root=tmp_path / "work",
                       unburned=unburned, source_pack=pack, repair_mode="worker")
    state = review_cycle.apply(session, actor="admin", action="approve_repair",
                               edits=[{"issue_id": "i1"}])
    assert state["request"]["revision_id"] == "r2"
    assert state["phase"] == "awaiting_admin"
    assert state["inspection"]["status"] == "clean"


def test_failed_inspection_can_retry_to_clean(tmp_path, monkeypatch):
    request, unburned, pack, _ = _fixture(tmp_path, monkeypatch, "failed_open")
    session = tmp_path / "session"
    state = review_cycle.start(request, session=session, work_root=tmp_path / "work",
                               unburned=unburned, source_pack=pack)
    assert state["phase"] == "inspection_failed"
    request2, _, _, _ = _fixture(tmp_path, monkeypatch, "clean")
    assert request2["item_id"] == request["item_id"]
    state = review_cycle.retry_inspection(session)
    assert state["phase"] == "release_ready"
