from dev_pb2.iterate import _next_request


def test_followup_round_is_bound_to_previous_repair():
    request = {"item_id": "one", "revision_id": "R1", "video_path": "old.mp4",
               "source_path": "old.py", "subtitle_path": "old.srt"}
    decision = {"idempotency_key": "a" * 64}
    repair = {"video_path": "new.mp4", "source_path": "new.py",
              "subtitle_path": "new.srt", "video_sha256": "b" * 64,
              "source_sha256": "c" * 64}
    next_request = _next_request(request, decision, repair)
    assert next_request["revision_id"] == "R1:pb2:" + "a" * 12
    assert next_request["video_path"] == "new.mp4"
    assert next_request["source_path"] == "new.py"
    assert next_request["video_sha256"] == "b" * 64
