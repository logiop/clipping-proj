import subprocess
from pathlib import Path

import pytest

from clipping import config
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


class FakePopen:
    """Stands in for subprocess.Popen: yields `lines` on stdout, exits with `code`."""

    def __init__(self, lines, code=0, calls=None):
        self.lines, self.code, self.calls = lines, code, calls

    def __call__(self, cmd, **kw):
        if self.calls is not None:
            self.calls.append((cmd, kw))
        self.stdout = iter(self.lines)
        self.returncode = None
        return self

    def wait(self, timeout=None):
        self.returncode = self.code
        return self.code

    def kill(self):
        self.returncode = -9


def test_measure_streams_ffmpeg_output():
    calls = []
    lines = (FIXTURES / "astats.txt").read_text().splitlines(keepends=True)
    assert loudness.measure(Path("a.m4a"), popen=FakePopen(lines, calls=calls)) == [-30.5, -12.25]
    cmd, kw = calls[0]
    assert loudness.FILTER in cmd
    assert "measure_perchannel=none" in loudness.FILTER and "key=lavfi.astats.Overall.RMS_level" in loudness.FILTER
    assert kw["stdout"] == subprocess.PIPE and "capture_output" not in kw


def test_measure_raises_on_failure():
    with pytest.raises(RuntimeError):
        loudness.measure(Path("a.m4a"), popen=FakePopen([], code=1))


def _synthetic(path: Path, seconds: int = 60) -> Path:
    """Quiet tone with a loud burst at 30-32 s."""
    expr = "sin(2*PI*440*t)*if(between(t,30,32),0.9,0.05)"
    subprocess.run([config.ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=48000:d={seconds}", "-ac", "2", str(path)], check=True)
    return path


def test_filter_output_is_small_and_values_sane(tmp_path):
    audio = _synthetic(tmp_path / "a.wav")
    proc = subprocess.run([config.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(audio),
                           "-af", loudness.FILTER, "-f", "null", "-"], capture_output=True)
    assert proc.returncode == 0
    assert len(proc.stdout) < 100_000  # per minute of audio
    per_sec = loudness.measure(audio)
    assert len(per_sec) in (59, 60, 61)
    assert per_sec[31] > per_sec[10] + 20
    assert 30 in [s for s, _ in loudness.spikes(per_sec)] or 31 in [s for s, _ in loudness.spikes(per_sec)]


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
