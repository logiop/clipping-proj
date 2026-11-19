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
    assert "bestaudio" in calls[0] and "*10.00-70.50" in calls[0]


def test_download_failure_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(audio.subprocess, "run", lambda cmd, **kw: Proc(1))
    with pytest.raises(RuntimeError):
        audio.download(STREAM, None, tmp_path / "a.m4a")
