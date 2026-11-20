import re
from pathlib import Path

from clipping import captions
from clipping.listen import transcript
from clipping.listen.transcript import Word


def w(text, start, end, prob=0.9):
    return Word(start, end, text, prob)


STYLE = captions.CaptionStyle()


def test_group_splits_on_gap():
    words = [w("a", 0, 0.2), w("b", 0.3, 0.5), w("c", 2.0, 2.2)]
    groups = captions.group(words, max_words=3, max_gap=0.6)
    assert [[x.text for x in g] for g in groups] == [["a", "b"], ["c"]]


def test_group_splits_on_max_words():
    words = [w(str(i), i * 0.3, i * 0.3 + 0.2) for i in range(5)]
    groups = captions.group(words, max_words=3)
    assert [len(g) for g in groups] == [3, 2]


def test_to_ass_has_sections_and_highlights_active_word():
    groups = [[w("hello", 0.0, 0.5), w("world", 0.5, 1.0)]]
    ass = captions.to_ass(groups, STYLE, y=1400)
    for section in ("[Script Info]", "[V4+ Styles]", "[Events]", "PlayResX: 1080", "PlayResY: 1920"):
        assert section in ass
    lines = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
    assert len(lines) == 2
    assert "0:00:00.00,0:00:00.50" in lines[0]
    assert "{\\c&H00FFFF&}hello{\\c&HFFFFFF&} world" in lines[0]
    assert "hello {\\c&H00FFFF&}world{\\c&HFFFFFF&}" in lines[1]
    assert "\\pos(540,1400)" in lines[0]


def test_to_ass_escapes_braces_and_backslash():
    ass = captions.to_ass([[w("a{b}c\\d", 0, 1)]], STYLE, y=1400)
    line = next(ln for ln in ass.splitlines() if ln.startswith("Dialogue:"))
    assert "a\\{b\\}c\\\\d" in line
    assert "a{b}" not in line


def test_to_ass_time_format_hours():
    ass = captions.to_ass([[w("x", 3661.25, 3662.0)]], STYLE, y=0)
    assert "1:01:01.25,1:01:02.00" in ass


def test_flags_non_english():
    assert captions.language_flags("hi", 0.99, [w("a", 0, 1)]) == ("non_english",)


def test_flags_low_language_prob():
    assert captions.language_flags("en", 0.5, [w("a", 0, 1)]) == ("non_english",)


def test_flags_nan_prob_never_passes():
    assert captions.language_flags("en", float("nan"), [w("a", 0, 1)]) == ("non_english",)


def test_flags_unknown_language():
    assert captions.language_flags("", float("nan"), [w("a", 0, 1)]) == ("non_english",)


def test_flags_low_confidence():
    assert captions.language_flags("en", 0.99, [w("a", 0, 1, 0.2), w("b", 1, 2, 0.3)]) == ("low_confidence",)


def test_flags_empty_words_low_confidence():
    assert captions.language_flags("en", 0.99, []) == ("low_confidence",)


def test_flags_both_in_order():
    assert captions.language_flags("hi", 0.99, []) == ("non_english", "low_confidence")


def test_flags_clean():
    assert captions.language_flags("en", 0.95, [w("a", 0, 1, 0.9)]) == ()


def test_make_applies_offset_and_flags(monkeypatch):
    calls = {}

    def fake(audio, model, words):
        calls.update(audio=audio, model=model, words=words)
        return [], [w("hey", 1.0, 1.5)], "en", 0.99

    monkeypatch.setattr(transcript, "whisper", fake)
    ass, flags = captions.make(Path("clip.wav"), offset=2.0)
    assert calls == {"audio": Path("clip.wav"), "model": "base", "words": True}
    assert flags == ()
    assert "0:00:03.00,0:00:03.50" in ass


def test_make_drops_words_shifted_before_zero(monkeypatch):
    words = [w("hi", 0.5, 1.0), w("yo", 1.5, 2.0)]
    monkeypatch.setattr(transcript, "whisper", lambda a, m, words_: ([], words, "en", 0.9))
    ass, _ = captions.make(Path("c.wav"), offset=-1.0)
    assert "hi" not in ass
    assert "0:00:00.50,0:00:01.00" in ass
