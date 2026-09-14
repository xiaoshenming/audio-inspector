from pathlib import Path

from audio_inspector.report import write_report


def test_report_escapes_untrusted_item_and_finding(tmp_path: Path):
    target = tmp_path / "report.html"
    write_report(target, {
        "total": 1,
        "succeeded": 1,
        "candidate_videos": 1,
        "failed_open": 0,
        "items": [{
            "status": "completed",
            "item": {"item_id": "x'><script>alert(1)</script>"},
            "evidence": {"findings": [{
                "severity": "high", "start_ms": 1000, "end_ms": 2000,
                "reason": "<img src=x>", "transcript_text": "</script>",
            }]},
        }],
    })
    page = target.read_text(encoding="utf-8")
    assert "<img src=x>" not in page
    assert "<script>alert(1)</script>" not in page
    assert "&lt;img src=x&gt;" in page
