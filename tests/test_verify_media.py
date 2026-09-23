import hashlib
import json

from dev_pb2 import verify_media


def test_candidate_video_is_verified_even_when_screening_still_flags_it(tmp_path,
                                                                          monkeypatch):
    video_dir = tmp_path / "repaired"
    video_dir.mkdir()
    video = video_dir / "final.mp4"
    video.write_bytes(b"full playable candidate video")
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    (video_dir / "repair-receipt.json").write_text(json.dumps({"video_sha256": digest}))
    summary = tmp_path / "combined-summary.json"
    summary.write_text(json.dumps({"rows": [{"item_id": "one",
        "final": "needs_review_or_repair", "latest_video_path": str(video)}]}))
    monkeypatch.setattr(verify_media, "_probe", lambda path: {
        "format": {"duration": "12"}, "streams": [
            {"codec_type": "video"}, {"codec_type": "audio"}]})
    result = verify_media.verify(summary)
    assert result["expected"] == result["verified"] == 1
    assert result["failed"] == 0
