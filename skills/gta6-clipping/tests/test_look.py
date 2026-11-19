from pathlib import Path

import cv2
import pytest
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

    kept = look.check(moments, "sonnet", ask=fake_ask).kept
    assert [m.start for m in kept] == [0]
    assert seen["tools"] == "Read" and seen["add_dir"] == Path("/w/frames")
    assert "/w/frames/b.jpg" in seen["prompt"]
    prompt = seen["prompt"]
    assert prompt.index("Moment 0 (0s-30s") < prompt.index("/w/frames/a.jpg") < prompt.index("Moment 1 (60s-90s")
    assert prompt.index("Moment 1 (60s-90s") < prompt.index("/w/frames/b.jpg")


def test_look_keeps_moment_without_verdict():
    result = look.check([(moment(), [Path("/w/frames/a.jpg")])], "sonnet",
                        ask=lambda *a, **k: {"verdicts": []})
    assert len(result.kept) == 1 and (result.failed, result.total) == (0, 1)


def test_look_fallback_when_claude_fails(tmp_path):
    static = (moment(0, 30), frames_for(tmp_path, "s", noisy=False))
    moving = (moment(60, 90), frames_for(tmp_path, "m", noisy=True))
    result = look.check([static, moving], "sonnet", ask=lambda *a, **k: None)
    assert [m.start for m in result.kept] == [60] and (result.failed, result.total) == (1, 1)


def test_look_empty_input_makes_no_call():
    def boom(*a, **k):
        raise AssertionError("should not call claude")
    assert look.check([], "sonnet", ask=boom) == look.LookResult([], 0, 0)


def test_look_ignores_out_of_range_and_duplicate_false_drops():
    items = [(moment(0, 30), [Path("/w/frames/a.jpg")]), (moment(60, 90), [Path("/w/frames/b.jpg")])]
    verdicts = [{"index": 7, "gameplay": False, "why": "x"},
                {"index": 0, "gameplay": True, "why": "ok"}, {"index": 0, "gameplay": False, "why": "menu"}]
    kept = look.check(items, "sonnet", ask=lambda *a, **k: {"verdicts": verdicts}).kept
    assert [m.start for m in kept] == [60]


def test_look_refuses_frames_dir_that_exposes_forbidden_path(tmp_path):
    work = tmp_path / "work"
    (work / "frames").mkdir(parents=True)
    ok = [(moment(), [work / "frames" / "a.jpg"])]
    bad = [(moment(), [work / "a.jpg"])]
    ask = lambda *a, **k: {"verdicts": []}
    assert len(look.check(ok, "sonnet", ask=ask, forbid=(work,)).kept) == 1
    with pytest.raises(ValueError):
        look.check(bad, "sonnet", ask=ask, forbid=(work,))
    with pytest.raises(ValueError):
        look.check(bad, "sonnet", ask=ask, forbid=(work / "stage.json",))


def test_look_fallback_keeps_moments_when_cv2_missing(monkeypatch, tmp_path):
    def no_cv2(frames):
        raise ImportError("no cv2")
    monkeypatch.setattr(look, "frame_diffs", no_cv2)
    items = [(moment(0, 30), frames_for(tmp_path, "s", noisy=False))]
    assert len(look.check(items, "sonnet", ask=lambda *a, **k: None).kept) == 1


def test_look_batches_five_moments_per_call_with_local_indices():
    items = [(moment(i * 100, i * 100 + 30), [Path(f"/w/frames/{i}/a.jpg")]) for i in range(12)]
    prompts = []

    def ask(prompt, schema, model, tools="", add_dir=None):
        prompts.append(prompt)
        drop_first = "/w/frames/5/a.jpg" in prompt  # second batch: reject its local index 0
        return {"verdicts": [{"index": 0, "gameplay": not drop_first, "why": "x"}]}

    result = look.check(items, "sonnet", ask=ask, parallel=3)
    assert len(prompts) == 3 and (result.failed, result.total) == (0, 3)
    assert all("Moment 5 " not in p for p in prompts)  # indices restart in every batch
    assert [m.start for m in result.kept] == [i * 100 for i in range(12) if i != 5]


def test_look_failing_batch_falls_back_alone(monkeypatch, capsys):
    items = [(moment(i * 100, i * 100 + 30), [Path(f"/w/frames/{i}/a.jpg")]) for i in range(7)]
    monkeypatch.setattr(look, "_fallback", lambda batch: [m for m, _ in batch][:1])

    def ask(prompt, schema, model, tools="", add_dir=None):
        return None if "/w/frames/0/a.jpg" in prompt else {"verdicts": []}

    result = look.check(items, "sonnet", ask=ask)
    assert [m.start for m in result.kept] == [0, 500, 600]
    assert (result.failed, result.total) == (1, 2)
    assert "visual check failed" in capsys.readouterr().err
