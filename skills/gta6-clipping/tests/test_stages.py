import json
import types
from pathlib import Path

import cv2
import numpy as np
import pytest

from clipping import stages
from clipping.config import paths
from clipping.layout import Box
from clipping.listen.transcript import Segment
from clipping.models import Moment, Stream

FIXTURES = Path(__file__).parent / "fixtures"
STREAM = Stream(id="youtube:abc", url="https://www.youtube.com/watch?v=abc", platform="youtube",
                streamer="@Kai", title="GTA 6", duration=7200.0, is_live=False)


def _m(start, score=50, flags=()):
    return Moment(start=start, end=start + 30, score=score, category="funny", event="other", hook="h",
                  caption="c", hashtags=("#gta6",), reason="r", flags=flags)


def _fake_listen(monkeypatch, calls):
    def download(stream, section, dest, cookies=None):
        calls.append(("download", section, cookies))
        dest.write_bytes(b"a")
        return dest

    monkeypatch.setattr(stages.audio, "download", download)
    monkeypatch.setattr(stages.loudness, "measure", lambda audio: [0.0] * 10)
    monkeypatch.setattr(stages.loudness, "spikes", lambda per_sec: [(3, 9.0)])
    monkeypatch.setattr(stages.transcript, "get",
                        lambda stream, audio, cookies=None, section=None: [Segment(3601.0, 3603.0, "wow")])
    monkeypatch.setattr(stages, "chat_bursts", lambda stream, work, section, cookies: [(3605, 4.0)])


def test_listen_stage_shifts_spikes_and_caches(tmp_path, monkeypatch):
    calls = []
    _fake_listen(monkeypatch, calls)
    opts = stages.Options(cookies="chrome")
    heard = stages.listen_stage(STREAM, tmp_path, (3600.0, 4200.0), opts)
    assert heard == ([Segment(3601.0, 3603.0, "wow")], [(3603.0, 9.0)], [(3605, 4.0)])
    assert calls == [("download", (3600.0, 4200.0), "chrome")]
    assert stages.listen_stage(STREAM, tmp_path, (3600.0, 4200.0), opts) == heard
    assert len(calls) == 1  # second run reads listen.json
    stages.listen_stage(STREAM, tmp_path, (3600.0, 4200.0), stages.Options(redo=True))
    assert len(calls) == 2


def test_pick_stage_asks_for_twice_the_clips_and_caches(tmp_path, monkeypatch):
    seen = []

    def fake_pick(stream, segments, spikes, bursts, n, model, parallel=4):
        seen.append((n, model, parallel))
        return [_m(100, flags=("x",))]

    monkeypatch.setattr(stages.pick, "pick", fake_pick)
    opts = stages.Options(clips=3, model="opus", pick_parallel=2)
    assert stages.pick_stage(STREAM, tmp_path, ([], [], []), opts) == [_m(100, flags=("x",))]
    assert stages.pick_stage(STREAM, tmp_path, ([], [], []), opts) == [_m(100, flags=("x",))]
    assert seen == [(6, "opus", 2)]


def test_look_stage_keeps_top_clips_sorted_by_start(tmp_path, monkeypatch):
    p = paths({"HOME": str(tmp_path), "CLIP_ARCHIVE": str(tmp_path / "arch")})
    work = p.work / "s"

    def frames(stream, m, frames_dir, cookies):
        if m.start == 900:
            raise RuntimeError("preview failed")
        frames_dir.mkdir(parents=True)
        f = frames_dir / "f.jpg"
        f.write_bytes(b"x")
        return [f]

    monkeypatch.setattr(stages.fetch, "moment_frames", frames)
    seen = {}

    def check(items, model, forbid=()):
        seen["items"], seen["forbid"] = items, forbid
        return [m for m, _ in items]

    monkeypatch.setattr(stages.look, "check", check)
    cands = [_m(500, 90), _m(100, 80), _m(300, 10), _m(900, 99)]
    kept = stages.look_stage(STREAM, work, cands, stages.Options(clips=2), p)
    assert kept == [_m(100, 80), _m(500, 90)]
    assert [m.start for m, _ in seen["items"]] == [500, 100, 300]
    assert seen["forbid"] == (p.work, work)
    assert stages.look_stage(STREAM, work, cands, stages.Options(clips=2), p) == kept  # cached


def test_look_stage_frames_dir_passes_real_forbid_check(tmp_path, monkeypatch):
    p = paths({"HOME": str(tmp_path), "CLIP_ARCHIVE": str(tmp_path / "arch")})
    work = p.work / "s"

    def frames(stream, m, frames_dir, cookies):
        frames_dir.mkdir(parents=True)
        f = frames_dir / "f.jpg"
        f.write_bytes(b"x")
        return [f]

    monkeypatch.setattr(stages.fetch, "moment_frames", frames)
    asked = {}

    def ask(prompt, schema, model, tools="", add_dir=None):
        asked["dir"] = add_dir
        return {"verdicts": []}

    real_check = stages.look.check
    monkeypatch.setattr(stages.look, "check", lambda items, model, forbid=(): real_check(items, model, ask=ask,
                                                                                          forbid=forbid))
    assert stages.look_stage(STREAM, work, [_m(100), _m(500)], stages.Options(), p) == [_m(100), _m(500)]
    assert asked["dir"] == (work / "frames").resolve()


def test_look_stage_without_candidates(tmp_path):
    p = paths({"HOME": str(tmp_path)})
    assert stages.look_stage(STREAM, tmp_path / "w", [], stages.Options(), p) == []


def _fake_clip_tools(monkeypatch, calls):
    def download_clip(stream, m, dest, cookies):
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "clip_raw.mp4"
        f.write_bytes(b"v")
        calls.append("download")
        return f

    def fake_render(src, out, plan, ass_path, hook, credit, fast):
        calls.append(("render", src.name, out.name, ass_path.name, hook, credit, fast, plan))
        out.write_bytes(b"r")
        return out

    monkeypatch.setattr(stages.fetch, "download_clip", download_clip)
    monkeypatch.setattr(stages, "layout_for", lambda clip, forced: f"plan-{forced}")
    monkeypatch.setattr(stages, "extract_wav", lambda clip, wav: wav)
    monkeypatch.setattr(stages.captions, "make", lambda wav, offset: ("ASS", ("non_english", "x")))
    monkeypatch.setattr(stages.render, "render", fake_render)


def test_clip_stage_renders_and_merges_flags(tmp_path, monkeypatch):
    calls = []
    _fake_clip_tools(monkeypatch, calls)
    opts = stages.Options(layout="face", fast=True)
    m, out, timings = stages.clip_stage(STREAM, tmp_path, "01", _m(100, flags=("x",)), opts)
    assert m.flags == ("x", "non_english")
    assert out == tmp_path / "out" / "01.mp4" and out.exists()
    assert (tmp_path / "clips" / "01.mp4").exists() and (tmp_path / "clips" / "01.ass").read_text() == "ASS"
    assert calls[-1] == ("render", "01.mp4", "01.mp4", "01.ass", "h", "@Kai", True, "plan-face")
    assert set(timings) == {"fetch", "layout", "captions", "render"}
    again = stages.clip_stage(STREAM, tmp_path, "01", _m(100, flags=("x",)), opts)
    assert again[0] == m and calls.count("download") == 1


def _write_video(path, w=64, h=48, n=12):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    for i in range(n):
        writer.write(np.full((h, w, 3), i * 10, dtype=np.uint8))
    writer.release()


def test_layout_for_samples_frames_and_plans(tmp_path):
    clip = tmp_path / "c.mp4"
    _write_video(clip)
    seen = []

    def detect(frame):
        seen.append(frame.shape)
        return [Box(2, 2, 6, 6)]

    plan = stages.layout_for(clip, "auto", detect=detect)
    assert len(seen) == stages.LAYOUT_SAMPLES
    assert plan.kind == "stream" and (plan.src_w, plan.src_h) == (64, 48)


def test_layout_for_unreadable_clip_raises(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"nope")
    with pytest.raises(RuntimeError):
        stages.layout_for(bad, "auto", detect=lambda f: [])


def test_extract_wav_runs_ffmpeg_mono_16k(tmp_path):
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"w")
        return types.SimpleNamespace(returncode=0, stderr="")

    wav = stages.extract_wav(tmp_path / "c.mp4", tmp_path / "c.wav", runner=runner)
    assert wav.exists() and ["-ac", "1"] == seen["cmd"][seen["cmd"].index("-ac"):][:2]
    assert "16000" in seen["cmd"]


def test_extract_wav_failure_raises(tmp_path):
    with pytest.raises(RuntimeError):
        stages.extract_wav(tmp_path / "c.mp4", tmp_path / "c.wav",
                           runner=lambda cmd, **kw: types.SimpleNamespace(returncode=1, stderr="bad"))


def test_chat_bursts_reads_live_chat_inside_section(tmp_path):
    lines = [json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": str(ms)}})
             for ms in [3_600_000 + i for i in range(0, 100_000, 1000)] + [3_700_000] * 60 + [10_000] * 99]

    def runner(cmd, **kw):
        out = Path(cmd[cmd.index("-o") + 1])
        Path(str(out) + ".live_chat.json").write_text("\n".join(lines))
        return types.SimpleNamespace(returncode=0, stderr="")

    got = stages.chat_bursts(STREAM, tmp_path, (3600.0, 4200.0), None, runner=runner)
    assert got and all(3600 <= start < 4200 for start, _ in got)


def test_chat_bursts_missing_chat_is_empty(tmp_path):
    runner = lambda cmd, **kw: types.SimpleNamespace(returncode=1, stderr="no chat")  # noqa: E731
    assert stages.chat_bursts(STREAM, tmp_path, None, None, runner=runner) == []
    twitch = Stream(id="t", url="u", platform="twitch", streamer="@a", title="t", duration=1.0, is_live=False)
    assert stages.chat_bursts(twitch, tmp_path, None, None, runner=lambda *a, **k: pytest.fail("no call")) == []


def test_chat_bursts_timeout_is_empty(tmp_path):
    import subprocess

    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    assert stages.chat_bursts(STREAM, tmp_path, None, None, runner=runner) == []


def test_cached_section_differs(tmp_path, monkeypatch):
    assert not stages.cached_section_differs(tmp_path, (1.0, 2.0))
    _fake_listen(monkeypatch, [])
    stages.listen_stage(STREAM, tmp_path, (3600.0, 4200.0), stages.Options())
    assert not stages.cached_section_differs(tmp_path, (3600.0, 4200.0))
    assert stages.cached_section_differs(tmp_path, (4110.0, 5000.0))
    assert stages.cached_section_differs(tmp_path, None)
