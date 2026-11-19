from pathlib import Path

from clipping.listen import loudness

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_astats_skips_inf():
    samples = loudness.parse_astats((FIXTURES / "astats.txt").read_text())
    assert samples == [(0.0, -30.5), (1.02, -12.25)]


def test_per_second_takes_max_and_fills_gaps():
    samples = [(0.1, -30.0), (0.6, -20.0), (3.2, -10.0)]
    assert loudness.per_second(samples) == [-20.0, -30.0, -30.0, -10.0]


def test_per_second_empty():
    assert loudness.per_second([]) == []


def test_spikes_finds_yell():
    per_sec = [-30.0] * 20
    per_sec[10] = -8.0
    result = loudness.spikes(per_sec)
    assert [s for s, _ in result] == [10]
    assert result[0][1] == 22.0


def test_spikes_flat_signal_has_none():
    assert loudness.spikes([-30.0] * 10) == []
    assert loudness.spikes([]) == []


def test_measure_uses_ffmpeg_output(monkeypatch):
    class Proc:
        returncode = 0
        stdout = (FIXTURES / "astats.txt").read_text()
        stderr = ""

    calls = []
    monkeypatch.setattr(loudness.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Proc())
    assert loudness.measure(Path("a.m4a")) == [-30.5, -12.25]
    assert "astats=metadata=1:reset=1,ametadata=print:file=-" in calls[0]


def test_measure_raises_on_failure(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(loudness.subprocess, "run", lambda cmd, **kw: Proc())
    import pytest
    with pytest.raises(RuntimeError):
        loudness.measure(Path("a.m4a"))


def test_spikes_half_silence_does_not_hide_yell():
    per_sec = [-30.0 + (i % 3) for i in range(30)] + [-91.0] * 30  # second half silent (fill value)
    per_sec[10] = -8.0
    assert [s for s, _ in loudness.spikes(per_sec)] == [10]


def test_spikes_ignore_seconds_below_silence_floor():
    per_sec = [-30.0 + (i % 3) for i in range(20)] + [-65.0, -70.0]
    assert loudness.spikes(per_sec) == []


def test_spikes_default_z_flags_top_of_compressed_speech():
    # loud, steadily compressed speech: the loudest few seconds still count as spikes
    per_sec = [-16.0 + ((i * 7) % 11) - 5 for i in range(200)]
    per_sec[50] = -6.0
    result = loudness.spikes(per_sec)
    assert 50 in [s for s, _ in result] and len(result) < 60
