from audio_inspector.literal_asr import target_clips
from audio_inspector.literal_reading import detect_one


def test_raw_fx_spoken_as_left_and_right_bracket_is_candidate(tmp_path):
    source = tmp_path / "main.py"
    source.write_text('class Scene:\n    def construct(self):\n'
                      '        with self.voiceover(text="已知函数 f(x) 的最大值为一"):\n'
                      '            pass\n')
    subtitle = tmp_path / "video.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:08,000\n已知函数 f(x) 的最大值为一\n")
    asr = {"status": "completed", "segments": [
        {"start_ms": 0, "end_ms": 7000,
         "text": "已知函数f左扣号x右扣号的最大值为一。"},
    ]}
    result = detect_one({"source_path": str(source), "subtitle_path": str(subtitle)}, asr)
    assert len(result) == 1
    assert result[0]["category"] == "audio_literal_formula"
    assert result[0]["confidence"] == "high"
    assert result[0]["line"] == 3
    assert result[0]["time_seconds"] == 0
    assert target_clips({"source_path": str(source), "subtitle_path": str(subtitle)}) == [
        {"start_seconds": 0.0, "end_seconds": 9.0},
    ]


def test_explicit_bracket_explanation_is_not_an_accidental_reading(tmp_path):
    source = tmp_path / "main.py"
    source.write_text('class Scene:\n    def construct(self):\n'
                      '        with self.voiceover(text="把 f(x) 的左括号读出来"):\n'
                      '            pass\n')
    asr = {"status": "completed", "segments": [
        {"start_ms": 0, "end_ms": 3000, "text": "把f左括号x右括号读出来"},
    ]}
    assert detect_one({"source_path": str(source), "subtitle_path": ""}, asr) == []


def test_point_coordinates_do_not_masquerade_as_function_call(tmp_path):
    source = tmp_path / "main.py"
    source.write_text('class Scene:\n    def construct(self):\n'
                      '        with self.voiceover(text="点 C(m,4) 在直线上"):\n'
                      '            pass\n')
    asr = {"status": "completed", "segments": [
        {"start_ms": 0, "end_ms": 3000, "text": "点C左括号m逗号4右括号在直线上"},
    ]}
    assert detect_one({"source_path": str(source), "subtitle_path": ""}, asr) == []


def test_latex_shell_is_matched_to_plain_subtitle(tmp_path):
    source = tmp_path / "main.py"
    source.write_text('class Scene:\n    def construct(self):\n'
                      '        with self.voiceover(text="求函数 $f(x)$ 的单调区间"):\n'
                      '            pass\n')
    subtitle = tmp_path / "video.srt"
    subtitle.write_text("1\n00:00:10,000 --> 00:00:16,000\n求函数 f(x) 的单调区间\n")
    record = {"source_path": str(source), "subtitle_path": str(subtitle)}
    assert target_clips(record) == [{"start_seconds": 9.0, "end_seconds": 17.0}]
    asr = {"status": "completed", "segments": [
        {"start_ms": 9000, "end_ms": 16000, "text": "求函数f左括号x右括号的单调区间"},
    ]}
    assert len(detect_one(record, asr)) == 1
