import json

from dev_pb2.summary import summarize


def test_summary_counts_only_reinspected_clean_videos(tmp_path):
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"cases": [
        {"request": {"item_id": "a"}, "original_priority": "A",
         "original_categories": ["source_missing_object"]},
        {"request": {"item_id": "b"}, "original_priority": "B",
         "original_categories": ["audio_literal_formula"]},
        {"request": {"item_id": "c"}, "original_priority": "A",
         "original_categories": ["audio_wrong_unit"]}]}))
    evaluation = tmp_path / "eval"
    for item_id, status in (("a", "closure_clean"), ("b", "closure_candidate"),
                            ("c", "needs_full_scene_rerender")):
        folder = evaluation / "cases" / item_id
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({"status": status,
                                                         "video_path": "local.mp4"}))
    (evaluation / "cases/b/iterations.json").write_text(json.dumps({
        "status": "closure_clean", "details": [
            {"after_status": "clean", "video_path": "round2.mp4"}]}))
    (evaluation / "cases/c/worker-result.json").write_text(json.dumps({
        "status": "closure_candidate", "video_path": "worker.mp4"}))
    result = summarize(batch, evaluation)
    assert result["final_counts"] == {"machine_clean": 2,
                                      "needs_review_or_repair": 1}
    assert result["literal_machine_clean"] == 1
    assert result["full_video_candidates"] == 3
    assert next(row for row in result["rows"] if row["item_id"] == "b")["video_path"] \
        == "round2.mp4"
