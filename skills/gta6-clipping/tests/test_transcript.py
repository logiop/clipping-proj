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

        def transcribe(self, audio, word_timestamps):
            assert audio == "decoded"
            return iter([seg]), info

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(transcript, "load_audio", lambda path: "decoded")
    segs, words, lang, prob = transcript.whisper(Path("a.m4a"), "tiny", True)
    assert (lang, prob) == ("it", 0.77)
    assert words[0].text == "hi" and segs[0].text == "hi"


def test_get_with_section_keeps_platform_captions_inside_it(monkeypatch):
    monkeypatch.setattr(transcript.ytdlp, "info", lambda *a, **k: {"subtitles": {"en": [{"ext": "vtt", "url": "u"}]}})
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nearly\n\n01:00:05.000 --> 01:00:07.000\ninside\n"
    monkeypatch.setattr(transcript, "_fetch_text", lambda url: vtt)
    assert transcript.get(STREAM, Path("a.m4a"), section=(3600.0, 4200.0)) == [Segment(3605.0, 3607.0, "inside")]


def test_get_with_section_shifts_whisper_to_stream_time(monkeypatch):
    monkeypatch.setattr(transcript.ytdlp, "info", lambda *a, **k: {})
    monkeypatch.setattr(transcript, "whisper", lambda audio, model, words: ([Segment(1.0, 2.0, "hi")], [], "en", 1.0))
    assert transcript.get(STREAM, Path("a.m4a"), section=(3600.0, 4200.0)) == [Segment(3601.0, 3602.0, "hi")]


def test_load_audio_decodes_with_ffmpeg_to_16k_mono_float(monkeypatch):
    import numpy as np
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout=np.array([0.5, -0.25], dtype="<f4").tobytes(), stderr=b"")

    out = transcript.load_audio(Path("a.m4a"), runner=runner)
    assert out.dtype == np.float32 and out.tolist() == [0.5, -0.25]
    cmd = seen["cmd"]
    assert cmd[cmd.index("-ar") + 1] == "16000" and cmd[cmd.index("-ac") + 1] == "1" and "f32le" in cmd


def test_load_audio_failure_raises():
    runner = lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"bad file")  # noqa: E731
    with pytest.raises(RuntimeError):
        transcript.load_audio(Path("a.m4a"), runner=runner)
