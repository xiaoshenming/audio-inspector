from audio_inspector.expected_text import extract_expected_voiceover


def test_extract_expected_voiceover_without_executing_source():
    code = '''
class Scene:
    def construct(self):
        with self.voiceover(text="第一句"):
            pass
        with self.voiceover(text=f"第二句"):
            pass
'''
    assert extract_expected_voiceover(code) == "第一句第二句"


def test_invalid_source_returns_empty_text():
    assert extract_expected_voiceover("not python !!!") == ""
