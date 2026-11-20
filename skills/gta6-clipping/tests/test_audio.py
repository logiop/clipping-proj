from pathlib import Path

import pytest

from clipping.listen import audio
from clipping.models import Stream

STREAM = Stream("abc", "https://x/abc", "youtube", "s", "t", 100.0, False)


class Proc:
    def __init__(self, code=0):
        self.returncode, self.stderr = code, "err"


def test_download_builds_section_command(monkeypatch, tmp_path):
    dest = tmp_path / "w" / "a.m4a"
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        dest.write_bytes(b"x")
        return Proc()

    monkeypatch.setattr(audio.subprocess, "run", fake_run)
    assert audio.download(STREAM, (10.0, 70.5), dest) == dest
    cmd = calls[0]
    assert "bestaudio" in cmd and "*10.00-70.50" in cmd and "--no-playlist" in cmd
    assert cmd[cmd.index("-o") + 1] == str(dest)
    loc = cmd[cmd.index("--ffmpeg-location") + 1]
    assert loc == str(Path(audio.config.ffmpeg_bin()).parent)


def test_download_failure_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.subprocess, "run", lambda cmd, **kw: Proc(1))
    with pytest.raises(RuntimeError):
        audio.download(STREAM, None, tmp_path / "a.m4a")


def test_download_continues_partial_instead_of_overwriting(monkeypatch, tmp_path):
    dest = tmp_path / "a.m4a"
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        dest.write_bytes(b"x")
        return Proc()

    monkeypatch.setattr(audio.subprocess, "run", fake_run)
    audio.download(STREAM, None, dest)
    assert "--continue" in calls[0] and "--force-overwrites" not in calls[0]


def test_download_reuses_a_complete_file(monkeypatch, tmp_path):
    dest = tmp_path / "a.m4a"
    dest.write_bytes(b"done")
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: pytest.fail("must not download again"))
    assert audio.download(STREAM, None, dest) == dest
