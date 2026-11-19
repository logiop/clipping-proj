import dataclasses
import json

from clipping import run
from clipping.config import paths
from clipping.models import Moment, Stream
from clipping.state import RunState

STREAM = Stream(id="youtube:abc", url="https://www.youtube.com/watch?v=abc", platform="youtube",
                streamer="@Kai", title="GTA 6", duration=7200.0, is_live=False)


def _moment(start, score=50):
    return Moment(start=start, end=start + 30, score=score, category="funny", event="other", hook="h",
                  caption="c", hashtags=("#gta6",), reason="r")


def _setup(tmp_path, monkeypatch, found, clipped=()):
    p = dataclasses.replace(paths({"CLIP_ARCHIVE": str(tmp_path / "arch")}), work=tmp_path / "work")
    p.archive.mkdir()
    touched = []
    monkeypatch.setattr(run.state, "load", lambda path: RunState(processed_until=0.0, clipped=tuple(clipped)))
    monkeypatch.setattr(run.stages, "listen_stage", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(run.stages, "pick_stage", lambda *a, **k: found)
    monkeypatch.setattr(run.stages, "look_stage", lambda stream, work, cands, opts, p: cands)
    for name in ("clip_stage",):
        monkeypatch.setattr(run.stages, name, lambda *a, **k: touched.append(name))
    monkeypatch.setattr(run.state, "save", lambda *a, **k: touched.append("state.save"))
    monkeypatch.setattr(run.archiving, "archive_stream", lambda *a, **k: touched.append("archive"))
    monkeypatch.setattr(run, "archive_stream", lambda *a, **k: touched.append("archive"), raising=False)
    monkeypatch.setattr(run.storage, "clean_work", lambda *a, **k: touched.append("clean"))
    return p, touched


def test_pick_only_does_not_archive_or_save_state(tmp_path, monkeypatch):
    p, touched = _setup(tmp_path, monkeypatch, [_moment(100), _moment(500)])
    opts = run.stages.Options(pick_only=True)
    assert run.process_stream(STREAM, opts, p, "2026-11-20") == []
    assert touched == []
    work = p.work / "youtubeabc"
    files = list(work.glob("compare_*.json"))
    assert len(files) == 1 and work.exists()
    data = json.loads(files[0].read_text())
    assert [m["start"] for m in data["moments"]] == [100, 500] and data["stream"]["id"] == "youtube:abc"
    assert "notes" in data


def test_pick_only_ignores_already_clipped(tmp_path, monkeypatch):
    p, _ = _setup(tmp_path, monkeypatch, [_moment(100), _moment(500)], clipped=[(100.0, 130.0)])
    run.process_stream(STREAM, run.stages.Options(pick_only=True), p, "2026-11-20")
    data = json.loads(next((p.work / "youtubeabc").glob("compare_*.json")).read_text())
    assert [m["start"] for m in data["moments"]] == [100, 500]


def test_cli_pick_only_flag():
    assert run.parse_args(["u", "--pick-only"]).pick_only is True
