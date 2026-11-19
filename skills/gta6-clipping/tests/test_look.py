from pathlib import Path

import cv2
import numpy as np

from clipping import look
from clipping.models import Moment


def moment(start=100.0, end=130.0):
    return Moment(start, end, 80, "funny", "other", "h", "c", ("gta6",), "r")


def write_frame(path: Path, value: int, noisy: bool = False) -> Path:
    rng = np.random.default_rng(int(path.stem.encode().hex(), 16) % 2**32)
    img = rng.integers(0, 255, (36, 64, 3), dtype=np.uint8) if noisy else np.full((36, 64, 3), value, np.uint8)
    cv2.imwrite(str(path), img)
    return path


def frames_for(tmp_path, tag, noisy):
    return [write_frame(tmp_path / f"{tag}{i}.jpg", 40, noisy) for i in range(4)]


def test_frame_times_inside_moment():
    times = look.frame_times(moment(100.0, 140.0), k=4)
    assert len(times) == 4
    assert all(100.0 < t < 140.0 for t in times)
    assert times == sorted(times)


def test_static_screen_detected():
    assert look.static_score([0.0, 0.1, 0.0]) > 0.98


def test_static_score_moving_is_low():
    assert look.static_score([30.0, 25.0, 40.0]) == 0.0
    assert look.static_score([]) == 0.0


def test_look_drops_non_gameplay():
    moments = [(moment(0, 30), [Path("/w/frames/a.jpg")]), (moment(60, 90), [Path("/w/frames/b.jpg")])]
    seen = {}

    def fake_ask(prompt, schema, model, tools="", add_dir=None, **kw):
        seen.update(tools=tools, add_dir=add_dir, prompt=prompt)
        return {"verdicts": [{"index": 0, "gameplay": True, "why": "driving"},
                             {"index": 1, "gameplay": False, "why": "BRB screen"}]}

    kept = look.check(moments, "sonnet", ask=fake_ask)
    assert [m.start for m in kept] == [0]
    assert seen["tools"] == "Read" and seen["add_dir"] == Path("/w/frames")
    assert "/w/frames/b.jpg" in seen["prompt"]


def test_look_keeps_moment_without_verdict():
    kept = look.check([(moment(), [Path("/w/frames/a.jpg")])], "sonnet",
                      ask=lambda *a, **k: {"verdicts": []})
    assert len(kept) == 1


def test_look_fallback_when_claude_fails(tmp_path):
    static = (moment(0, 30), frames_for(tmp_path, "s", noisy=False))
    moving = (moment(60, 90), frames_for(tmp_path, "m", noisy=True))
    kept = look.check([static, moving], "sonnet", ask=lambda *a, **k: None)
    assert [m.start for m in kept] == [60]


def test_look_empty_input_makes_no_call():
    def boom(*a, **k):
        raise AssertionError("should not call claude")
    assert look.check([], "sonnet", ask=boom) == []
