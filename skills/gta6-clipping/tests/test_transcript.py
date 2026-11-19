from pathlib import Path

from clipping.listen import transcript
from clipping.listen.transcript import Segment
from clipping.models import Stream

FIXTURES = Path(__file__).parent / "fixtures"
STREAM = Stream("abc", "https://x/abc", "youtube", "s", "t", 100.0, False)


def test_parse_vtt_dedupes_rolling_lines():
    segs = transcript.parse_vtt((FIXTURES / "rolling.vtt").read_text())
    assert [s.text for s in segs] == ["hello everyone welcome", "to the stream", "this is GTA 6"]
    assert segs[0].start == 1.0 and segs[2].end == 7.0


def test_find_caption_url_prefers_manual_en():
    info = {
        "subtitles": {"en-US": [{"ext": "vtt", "url": "manual"}]},
        "automatic_captions": {"en": [{"ext": "vtt", "url": "auto"}]},
    }
    assert transcript.find_caption_url(info) == "manual"


def test_find_caption_url_falls_back_to_auto_and_none():
    auto = {"automatic_captions": {"en": [{"ext": "json3", "url": "j"}, {"ext": "vtt", "url": "auto"}]}}
    assert transcript.find_caption_url(auto) == "auto"
    assert transcript.find_caption_url({"subtitles": {"it": [{"ext": "vtt", "url": "x"}]}}) is None


def test_get_uses_captions(monkeypatch):
    monkeypatch.setattr(transcript.ytdlp, "info", lambda *a, **k: {"subtitles": {"en": [{"ext": "vtt", "url": "u"}]}})
    monkeypatch.setattr(transcript, "_fetch_text", lambda url: (FIXTURES / "rolling.vtt").read_text())
    segs = transcript.get(STREAM, Path("a.m4a"))
    assert len(segs) == 3


def test_get_falls_back_to_whisper(monkeypatch):
    monkeypatch.setattr(transcript.ytdlp, "info", lambda *a, **k: {})
    seen = {}

    def fake_whisper(audio, model, words):
        seen["model"] = model
        return [Segment(0.0, 1.0, "hi")], [], "en", 0.9

    monkeypatch.setattr(transcript, "whisper", fake_whisper)
    assert transcript.get(STREAM, Path("a.m4a")) == [Segment(0.0, 1.0, "hi")]
    assert seen["model"] == "tiny"


def test_get_falls_back_when_info_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(transcript.ytdlp, "info", boom)
    monkeypatch.setattr(transcript, "whisper", lambda audio, model, words: ([Segment(0, 1, "w")], [], "en", 1.0))
    assert transcript.get(STREAM, Path("a.m4a"))[0].text == "w"
