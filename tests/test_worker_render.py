from uuid import UUID

from dev_pb2 import worker_render
from dev_pb2.worker_render import _capability, build_job


def test_worker_job_uses_locked_source_and_isolated_artifact_signing():
    generation = UUID("1f9b01dd-5862-492a-8e6d-68e44c167260")
    locator = "tos://bucket/dev-pb2/one/source.tar"
    job = build_job(generation, "one", locator, "a" * 64, "b" * 64,
                    tenant_id="tenant-test1", intake_url="http://intake:8810",
                    signing_secret="secret", bucket="bucket")
    assert job["profile"] == "delivery_high"
    assert job["source"]["locked"] is True
    assert job["source"]["sha256"] == "a" * 64
    assert job["source"]["download_signing_token"] == _capability(
        generation, "secret", locator)
    assert job["output"]["upload_signing_token"] == _capability(generation, "secret")
    assert job["output"]["uri_prefix"].startswith("tos://bucket/batchops-render/")
    hostile = build_job(generation, "../other/customer", locator, "a" * 64,
                        "b" * 64, tenant_id="tenant-test1",
                        intake_url="http://intake:8810", signing_secret="secret",
                        bucket="bucket")
    assert "/" not in hostile["batch_id"]
    assert ".." not in hostile["batch_id"]


def test_worker_result_is_reinspected_as_new_revision(tmp_path, monkeypatch):
    request = {"item_id": "one", "revision_id": "R1", "video_path": "old.mp4",
               "source_path": "old.py", "subtitle_path": "old.srt",
               "render_profile": {"aspect_ratio": "9:16", "quality": "m",
                                  "pixel_width": 720, "pixel_height": 1280,
                                  "frame_rate": 30},
               "tts_profile": {"provider": "qwen_audio", "model": "test-model",
                               "voice": "another-voice", "speech_rate": 1.1}}
    render = {"item_id": "one", "render_job_id": "job-1", "video_path": "new.mp4",
              "video_sha256": "a" * 64, "source_path": "new.py",
              "source_sha256": "b" * 64, "subtitle_path": "new.srt",
              "subtitle_sha256": "c" * 64}
    seen = {}
    def render_stub(*args, **kwargs):
        assert kwargs["render_profile"]["aspect_ratio"] == "9:16"
        assert kwargs["tts_profile"]["voice"] == "another-voice"
        return render

    monkeypatch.setattr(worker_render, "render_full", render_stub)

    def inspect(value, work_root):
        seen.update(value)
        return {"status": "clean"}

    monkeypatch.setattr(worker_render, "inspect_video", inspect)
    result = worker_render.render_and_inspect(request, tmp_path / "source.tar",
                                              tmp_path / "main.py", tmp_path / "result",
                                              tmp_path / "work")
    assert result["status"] == "reinspection_clean"
    assert seen["revision_id"] == "R1:worker:job-1"
    assert seen["video_path"] == "new.mp4"
    assert seen["subtitle_sha256"] == "c" * 64
