import json

from dev_pb2 import worker_batch


def test_worker_fallback_includes_second_round_duration_failures(tmp_path, monkeypatch):
    cases = [{"request": {"item_id": name}} for name in ("first", "second")]
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"cases": cases}))
    evaluation = tmp_path / "eval"
    for name, status in (("first", "needs_full_scene_rerender"),
                         ("second", "closure_candidate")):
        folder = evaluation / "cases" / name
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({"status": status}))
    (evaluation / "cases/second/iterations.json").write_text(json.dumps({
        "status": "retry_failed", "details": [
            {"error": "ValueError: replacement_duration_requires_scene_rerender"}]}))
    seen = []

    def one(case, eval_root, work_root):
        seen.append(case["request"]["item_id"])
        return {"item_id": seen[-1], "status": "closure_clean"}

    monkeypatch.setattr(worker_batch, "_one", one)
    summary = worker_batch.run_batch(batch, evaluation, tmp_path / "work", workers=1)
    assert summary["eligible"] == 2
    assert set(seen) == {"first", "second"}
