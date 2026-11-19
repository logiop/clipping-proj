import math
import sys
import types
from pathlib import Path

import pytest

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
    monkeypatch.setattr(transcript, "whisper", lambda *a, **k: pytest.fail("whisper must not run"))
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


def test_get_reports_failure_on_stderr_and_passes_cookies(monkeypatch, capsys):
    seen = {}

    def boom(url, cookies, extra=()):
        seen["cookies"] = cookies
        raise RuntimeError("x")

    monkeypatch.setattr(transcript.ytdlp, "info", boom)
    monkeypatch.setattr(transcript, "whisper", lambda audio, model, words: ([Segment(0, 1, "w")], [], "en", 1.0))
    transcript.get(STREAM, Path("a.m4a"), cookies="chrome")
    assert seen["cookies"] == "chrome"
    assert "RuntimeError" in capsys.readouterr().err


def test_whisper_mlx_missing_language_is_unknown(monkeypatch):
    stub = types.SimpleNamespace(transcribe=lambda *a, **k: {"segments": [{"start": 0, "end": 1, "text": " hi "}]})
    monkeypatch.setitem(sys.modules, "mlx_whisper", stub)
    segs, words, lang, prob = transcript.whisper(Path("a.m4a"), "tiny", False)
    assert segs == [Segment(0, 1, "hi")] and words == []
    assert lang == "" and math.isnan(prob)
    assert not (lang == "en" and prob >= 0.6)


def test_whisper_faster_passes_language_through(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # forces ImportError
    word = types.SimpleNamespace(start=0.0, end=0.5, word=" hi", probability=0.9)
    seg = types.SimpleNamespace(start=0.0, end=1.0, text=" hi ", words=[word])
    info = types.SimpleNamespace(language="it", language_probability=0.77)

    class Model:
        def __init__(self, name, **kw):
            pass

        def transcribe(self, path, word_timestamps):
            return iter([seg]), info

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    segs, words, lang, prob = transcript.whisper(Path("a.m4a"), "tiny", True)
    assert (lang, prob) == ("it", 0.77)
    assert words[0].text == "hi" and segs[0].text == "hi"
