from dev_pb2 import qwen_asr
from dev_pb2.qwen_asr import _decode_events, _response_events


def test_cumulative_qwen_events_become_incremental_timed_segments():
    events = [
        {"output": {"text": "已知A", "sentence": {
            "sentence_end": True, "sentence_id": 1, "begin_time": 100, "end_time": 900,
            "text": "已知A", "words": [
                {"text": "已知", "begin_time": 100, "end_time": 500},
                {"text": "A", "begin_time": 600, "end_time": 900},
            ]}}},
        {"output": {"text": "已知A与B", "sentence": {
            "sentence_end": True, "sentence_id": 2, "begin_time": 100, "end_time": 1800,
            "text": "已知A与B", "words": [
                {"text": "已知", "begin_time": 100, "end_time": 500},
                {"text": "A", "begin_time": 600, "end_time": 900},
                {"text": "与", "begin_time": 1100, "end_time": 1300},
                {"text": "B", "begin_time": 1500, "end_time": 1800},
            ]}}},
    ]
    result = _decode_events(events, 5000)
    assert result["text"] == "已知A与B"
    assert [row["text"] for row in result["segments"]] == ["已知A", "与B"]
    assert [(row["start_ms"], row["end_ms"]) for row in result["segments"]] == [
        (5100, 5900), (6100, 6800),
    ]


def test_nonstream_qwen_json_is_one_event():
    assert _response_events(b'{"output":{"text":"hello"}}')[0]["output"]["text"] == "hello"


def test_fractional_tail_after_chunk_boundary_is_transcribed(monkeypatch):
    starts = []
    monkeypatch.setattr(qwen_asr, "_duration", lambda _: 240.5)

    def audio(_path, start, seconds):
        starts.append((start, seconds))
        return b"audio"

    monkeypatch.setattr(qwen_asr, "_audio_chunk", audio)
    monkeypatch.setattr(qwen_asr, "_transcribe_chunk", lambda *_: {
        "text": "ok", "segments": []})
    qwen_asr.transcribe("sample.mp4", "key", "endpoint")
    assert starts == [(0, 240), (240, 0.5)]
