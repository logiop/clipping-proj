"""process_stream when clips fail, and CLI count validation (split from test_run.py)."""
import json

import pytest

from clipping import archiving, run
from clipping.run import out_dir, parse_args
from test_run import STREAM, _clock, _fake_clip_stage, _fake_stages, _moment, _real_stick, _tmp_paths


def _clip_stage_failing_at(start):
    def clip_stage(stream, work, nn, m, opts):
        if m.start == start:
            raise RuntimeError("ffmpeg render failed: boom")
        return _fake_clip_stage(stream, work, nn, m, opts)
    return clip_stage


def test_one_failing_clip_does_not_block_the_others(tmp_path, monkeypatch, capsys):
    p = _tmp_paths(tmp_path)
    _real_stick(monkeypatch, tmp_path)
    _fake_stages(monkeypatch, [[_moment(100), _moment(500)]])
    monkeypatch.setattr(run.stages, "clip_stage", _clip_stage_failing_at(100))
    monkeypatch.setattr(run.stages, "pick_stage", lambda stream, work, heard, opts: (
        run.stages.add_notes(work, pick_failed_chunks=1, pick_chunks=5), [_moment(100), _moment(500)])[1])
    monkeypatch.setattr(archiving, "datetime", _clock(["120000"]))
    saved = []
    monkeypatch.setattr(run.state, "save", lambda path, s, root: saved.append(s))
    archived = run.process_stream(STREAM, run.stages.Options(keep_work=True), p, "2026-11-19")
    assert [f.name for f in archived][0] == "02.mp4" and len(archived) == 4
    assert saved[0].clipped == ((500, 530),)  # the failed moment is not marked clipped
    report = json.loads((out_dir(p, STREAM, "2026-11-19") / "report_120000.json").read_text())
    assert report["failed_clips"] == 1 and report["pick_failed_chunks"] == 1 and report["clips"] == 1
    assert "clip 01 failed" in capsys.readouterr().out


def test_every_clip_failing_fails_the_stream_and_keeps_work(tmp_path, monkeypatch):
    p = _tmp_paths(tmp_path)
    _fake_stages(monkeypatch, [[_moment(100)]])
    monkeypatch.setattr(run.stages, "clip_stage", _clip_stage_failing_at(100))
    monkeypatch.setattr(run.state, "save", lambda *a, **k: pytest.fail("state must not change"))
    with pytest.raises(RuntimeError, match="all 1 clips failed"):
        run.process_stream(STREAM, run.stages.Options(), p, "2026-11-19")
    assert (p.work / "youtubeabc").exists()


@pytest.mark.parametrize("flag", ["--clips", "--streams", "--pick-parallel", "--parallel"])
@pytest.mark.parametrize("value", ["0", "-1", "x"])
def test_cli_counts_must_be_at_least_one(flag, value, capsys):
    with pytest.raises(SystemExit):
        parse_args([flag, value])
    assert flag in capsys.readouterr().err
    assert getattr(parse_args([flag, "2"]), flag.lstrip("-").replace("-", "_")) == 2
