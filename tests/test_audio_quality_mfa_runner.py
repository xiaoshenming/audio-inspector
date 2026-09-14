from pathlib import Path

import pytest

from audio_inspector import mfa_runner


def test_missing_dictionary_is_explicit_review_cause(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("STT_MFA_DICTIONARY", raising=False)
    with pytest.raises(RuntimeError, match="missing STT_MFA_DICTIONARY"):
        mfa_runner.analyze_pronunciation(
            str(tmp_path / "video.mp4"),
            expected_text="长方形",
            manifest={"entries": [{"text": "长", "phones": ["ch", "ang2"]}]},
        )
