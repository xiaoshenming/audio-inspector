from audio_inspector.contract import completed_payload, failed_payload, finding


def test_completed_payload_separates_visible_and_record_only_findings():
    findings = [
        finding(
            finding_id="high-1",
            finding_type="stt_english_leak",
            severity="high",
            start=1.25,
            end=2.5,
            transcript="prime",
            reason="英文泄漏",
        ),
        finding(
            finding_id="low-1",
            finding_type="stt_latin_token",
            severity="low",
            start=3,
            end=4,
            transcript="A B C",
            reason="普通几何字母",
        ),
    ]
    payload, evidence = completed_payload(
        model="faster-whisper-small",
        audio_duration_ms=10000,
        inference_ms=2000,
        model_load_ms=500,
        findings=findings,
    )
    assert payload["summary"] == {
        "confirmed_issue_count": 0,
        "candidate_risk_count": 1,
        "visible_risk_count": 1,
        "record_only_count": 1,
        "high": 1,
        "medium": 0,
        "low": 1,
    }
    assert payload["real_time_factor"] == 0.2
    assert evidence["findings"][0]["start_ms"] == 1250


def test_failed_payload_is_explicitly_fail_open():
    payload = failed_payload("x" * 1200)
    assert payload["status"] == "failed_open"
    assert payload["fail_open"] is True
    assert len(payload["error"]) == 1000


def test_confirmation_depends_on_explicit_decision_not_finding_type():
    item = finding(
        finding_id="model-1",
        finding_type="phoneme_model_result",
        severity="high",
        start=None,
        end=None,
        transcript="",
        reason="独立模型已确认",
        decision="confirmed",
    )
    payload, _evidence = completed_payload(
        model="faster-whisper-small",
        audio_duration_ms=1000,
        inference_ms=100,
        model_load_ms=0,
        findings=[item],
    )
    assert payload["summary"]["confirmed_issue_count"] == 1
    assert payload["summary"]["candidate_risk_count"] == 0
