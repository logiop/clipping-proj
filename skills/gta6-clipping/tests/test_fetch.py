from pathlib import Path
from types import SimpleNamespace

import pytest

from clipping import fetch
from clipping.models import Moment, Stream

STREAM = Stream(id="s1", url="https://x/v", platform="twitch", streamer="Foo", title="t",
                duration=3600.0, is_live=False)


def moment(start=100.0, end=130.0):
    return Moment(start, end, 80, "funny", "other", "h", "c", ("gta6",), "r")


def test_clip_section_pads_and_clamps_at_zero():
    assert fetch.clip_section(moment(100, 130)) == (98.0, 132.0)
    assert fetch.clip_section(moment(1.0, 20.0), pad=2.0) == (0.0, 22.0)


def recorder(create=True):
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        if create:
            out = Path(argv[argv.index("-o") + 1])
            out.write_bytes(b"x")
        return SimpleNamespace(returncode=0, stderr="")
    return runner, calls


def test_download_clip_uses_1080_format_and_section(tmp_path):
    runner, calls = recorder()
    out = fetch.download_clip(STREAM, moment(), tmp_path, None, runner=runner)
    argv = calls[0]
    assert out.parent == tmp_path and out.exists()
    assert argv[argv.index("-f") + 1] == "bv*[height<=1080]+ba/b[height<=1080]"
    assert argv[argv.index("--download-sections") + 1] == "*98.00-132.00"
    assert "--force-keyframes-at-cuts" in argv and "--no-playlist" in argv
    assert argv[-1] == STREAM.url


def test_download_preview_uses_360(tmp_path):
    runner, calls = recorder()
    fetch.download_preview(STREAM, moment(), tmp_path, None, runner=runner)
    assert calls[0][calls[0].index("-f") + 1] == "bv*[height<=360]"


def test_download_failure_raises(tmp_path):
    def runner(argv, **kw):
        return SimpleNamespace(returncode=1, stderr="boom")
    with pytest.raises(RuntimeError, match="boom"):
        fetch.download_clip(STREAM, moment(), tmp_path, None, runner=runner)


def test_extract_frames_runs_ffmpeg_per_offset(tmp_path):
    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"jpg")
        return SimpleNamespace(returncode=0, stderr="")
    preview = tmp_path / "p.mp4"
    frames = fetch.extract_frames(preview, [3.0, 9.5], tmp_path / "frames", "m0", runner=runner)
    assert len(frames) == 2 and all(f.suffix == ".jpg" and f.exists() for f in frames)
    assert calls[0][calls[0].index("-ss") + 1] == "3.00"
