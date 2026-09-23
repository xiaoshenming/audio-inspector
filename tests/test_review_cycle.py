import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from dev_pb2 import review_cycle


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pack(path, source):
    data = source.read_bytes()
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("main.py")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))


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
    _write_pack(pack, source)
    request = {"item_id": "one", "revision_id": "r1", "video_path": str(video),
               "source_path": str(source), "subtitle_path": str(subtitle),
               "subtitle_sha256": _sha(subtitle),
               "render_profile": {"aspect_ratio": "16:9", "quality": "m",
                                  "pixel_width": 1280, "pixel_height": 720,
                                  "frame_rate": 30},
               "tts_profile": {"provider": "qwen_audio",
                               "model": "qwen-audio-3.0-tts-plus",
                               "voice": "longanlufeng", "speech_rate": 0.9}}

    def inspect(current, _work):
        assert current["subtitle_sha256"] == _sha(Path(current["subtitle_path"]))
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
        output = kwargs["output"]
        output.mkdir(parents=True, exist_ok=True)
        new_video = output / "final.mp4"
        new_source = output / "main.py"
        new_srt = output / "corrected.srt"
        new_pack = output / "source.tar"
        if not new_video.exists():
            calls.append(decision)
            new_video.write_bytes(b"repaired video")
            new_source.write_text('self.voiceover(text="求 a 的值。")\n', encoding="utf-8")
            new_srt.write_text("repaired")
            (output / "corrected-unburned.mp4").write_bytes(b"new unburned")
            _write_pack(new_pack, new_source)
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


def test_local_repair_assets_require_original_voice_profile(tmp_path, monkeypatch):
    request, unburned, pack, _ = _fixture(tmp_path, monkeypatch)
    request.pop("tts_profile")
    with pytest.raises(TypeError, match="tts_profile_required"):
        review_cycle.start(request, session=tmp_path / "session",
                           work_root=tmp_path / "work", unburned=unburned,
                           source_pack=pack)


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


@pytest.mark.parametrize("resource", ["subtitle", "unburned", "source_pack"])
def test_admin_cannot_use_changed_review_resource(tmp_path, monkeypatch, resource):
    request, unburned, pack, _ = _fixture(tmp_path, monkeypatch)
    session = tmp_path / "session"
    review_cycle.start(request, session=session, work_root=tmp_path / "work",
                       unburned=unburned, source_pack=pack)
    path = {"subtitle": Path(request["subtitle_path"]),
            "unburned": unburned, "source_pack": pack}[resource]
    path.write_bytes(b"changed resource")
    with pytest.raises(ValueError, match=f"stale_{resource}_revision|source_pack_main"):
        review_cycle.apply(session, actor="admin", action="approve_repair",
                           edits=[{"issue_id": "i1"}], api_key="test",
                           tts_endpoint="test")


def test_busy_review_session_rejects_a_second_decision(tmp_path, monkeypatch):
    request, unburned, pack, _ = _fixture(tmp_path, monkeypatch)
    session = tmp_path / "session"
    review_cycle.start(request, session=session, work_root=tmp_path / "work",
                       unburned=unburned, source_pack=pack)
    with review_cycle._locked(session), pytest.raises(ValueError, match="session_busy"):
        review_cycle.apply(session, actor="second", action="accept_as_is")


def test_crash_after_repair_requires_resume_of_same_approved_decision(tmp_path, monkeypatch):
    request, unburned, pack, calls = _fixture(tmp_path, monkeypatch)
    session = tmp_path / "session"
    review_cycle.start(request, session=session, work_root=tmp_path / "work",
                       unburned=unburned, source_pack=pack)
    real_run = review_cycle.run
    fail = {"once": True}

    def interrupted(current, work):
        if current["revision_id"] != "r1" and fail["once"]:
            fail["once"] = False
            raise RuntimeError("interrupted_reinspection")
        return real_run(current, work)

    monkeypatch.setattr(review_cycle, "run", interrupted)
    with pytest.raises(RuntimeError, match="interrupted_reinspection"):
        review_cycle.apply(session, actor="admin", action="approve_repair",
                           edits=[{"issue_id": "i1"}], api_key="test", tts_endpoint="test")
    pending = review_cycle.load(session)
    assert pending["phase"] == "repairing"
    assert pending["request"]["video_path"] == request["video_path"]
    with pytest.raises(ValueError, match="not_awaiting_admin"):
        review_cycle.apply(session, actor="other", action="approve_repair",
                           edits=[{"issue_id": "i1", "new_text": "别的文字"}])
    resumed = review_cycle.resume_repair(session, api_key="test", tts_endpoint="test")
    assert resumed["phase"] == "awaiting_admin"
    assert resumed["round"] == 1
    assert len(calls) == 1


def test_worker_route_returns_to_admin_with_new_revision(tmp_path, monkeypatch):
    request, unburned, pack, _ = _fixture(tmp_path, monkeypatch)
    session = tmp_path / "session"

    def patched(_pack, overrides, output):
        assert overrides[0]["new_voiceover"] == "求 a 的值。"
        output.mkdir(parents=True)
        main = output / "main.py"
        main.write_text('self.voiceover(text="求 a 的值。")\n', encoding="utf-8")
        _write_pack(output / "source.tar", main)
        return main

    def rendered(current, _pack, main, output, _work, job_item_id=None):
        assert job_item_id.startswith("one-pb2-")
        output.mkdir(parents=True)
        video = output / "final.mp4"
        video.write_bytes(b"worker video")
        subtitle = output / "final.srt"
        subtitle.write_text("repaired")
        revised = {**current, "revision_id": "r2", "video_path": str(video),
                   "source_path": str(main), "subtitle_path": str(subtitle),
                   "subtitle_sha256": _sha(subtitle)}
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
