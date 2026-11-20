import json
from pathlib import Path

import pytest

from clipping.config import paths
from clipping.models import Moment
from clipping.state import RunState, advance, already_clipped, load, next_section, save, state_file
from clipping.storage import UnsafePathError

EXT = -1  # fake home device id: tmp_path then counts as "external"


def _m(start, end):
    return Moment(start=start, end=end, score=50, category="funny", event="other", hook="h",
                  caption="c", hashtags=("#gta6",), reason="r")


def test_next_section_overlaps():
    assert next_section(RunState(processed_until=3600), 7200) == (3510, 7200)


def test_next_section_starts_at_zero_for_new_stream():
    assert next_section(RunState(), 600) == (0, 600)


def test_next_section_none_when_nothing_new():
    assert next_section(RunState(processed_until=7200), 7200) is None
    assert next_section(RunState(processed_until=7200), 7000) is None


def test_skips_already_clipped():
    s = RunState(processed_until=3600, clipped=((100.0, 130.0),))
    assert already_clipped(s, _m(110, 140))
    assert already_clipped(s, _m(140, 170))  # within the 20 s tolerance
    assert not already_clipped(s, _m(300, 330))


def test_advance_returns_new_state():
    s = RunState(processed_until=100, clipped=((10.0, 40.0),))
    s2 = advance(s, 7200, [_m(500, 530)])
    assert s2 is not s
    assert s == RunState(processed_until=100, clipped=((10.0, 40.0),))
    assert s2.processed_until == 7200
    assert s2.clipped == ((10.0, 40.0), (500, 530))


def test_advance_never_moves_backwards():
    assert advance(RunState(processed_until=900), 300, []).processed_until == 900


def test_state_file_lives_in_archive(tmp_path):
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    assert state_file(p, "yt:abc/../x").parent == p.state


def test_load_missing_file_is_empty_state(tmp_path):
    assert load(tmp_path / "nope.json") == RunState()


def test_save_then_load_round_trip(tmp_path):
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    path = state_file(p, "youtube:abc")
    s = RunState(processed_until=42.5, clipped=((1.0, 20.0),))
    save(path, s, p.archive, home_dev=EXT)
    assert load(path) == s
    assert json.loads(path.read_text())["processed_until"] == 42.5
    assert not path.with_name(path.name + ".part").exists()


def test_save_refuses_outside_root(tmp_path):
    root = tmp_path / "arch"; root.mkdir()
    with pytest.raises(UnsafePathError):
        save(tmp_path / "elsewhere.json", RunState(), root, home_dev=EXT)


def test_save_refuses_missing_archive_root(tmp_path):
    root = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        save(root / "gta6-clips" / "state" / "x.json", RunState(), root, home_dev=EXT)
    assert not root.exists()


def test_save_refuses_archive_root_that_is_a_mount_point(tmp_path, monkeypatch):
    from clipping import storage
    root = tmp_path / "stick"
    root.mkdir()
    monkeypatch.setattr(storage.os.path, "ismount", lambda p: Path(p).resolve() == root.resolve())
    with pytest.raises(FileNotFoundError):
        save(root / "gta6-clips" / "state" / "x.json", RunState(), root, home_dev=EXT)
    assert not (root / "gta6-clips").exists()
