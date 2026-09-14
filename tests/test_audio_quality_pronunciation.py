from pathlib import Path

from audio_inspector.decision import decide
from audio_inspector.mfa_evidence import compare_manifest
from audio_inspector.pronunciation_manifest import PronunciationEntry, build_manifest


def test_manifest_mismatch_is_confirmed(tmp_path: Path) -> None:
    grid = tmp_path / "sample.TextGrid"
    grid.write_text(_grid("多重", ["t", "w", "o˥", "ʈʂʰ", "u˧˥", "ŋ"]))
    manifest = build_manifest([PronunciationEntry(
        text="多重", pinyin="duo1 zhong4",
        phones=("t", "w", "o˥", "ʈʂ", "u˥˩", "ŋ"),
        source="tts_hot_fix", confidence=1.0,
    )])
    finding = compare_manifest(grid, manifest)[0]
    assert finding["decision"] == "confirmed"


def test_missing_lane_requires_review() -> None:
    result = decide([], required_lanes=["asr", "pronunciation"], completed_lanes=["asr"])
    assert result["verdict"] == "needs_review"


def _grid(word: str, phones: list[str]) -> str:
    intervals = []
    for index, phone in enumerate(phones, 1):
        intervals.append(
            f'intervals [{index}]:\n xmin = {(index - 1) / len(phones)}\n'
            f' xmax = {index / len(phones)}\n text = "{phone}"'
        )
    return (
        'name = "words"\nintervals [1]:\n xmin = 0\n xmax = 1\n'
        f' text = "{word}"\nname = "phones"\n' + "\n".join(intervals)
    )
