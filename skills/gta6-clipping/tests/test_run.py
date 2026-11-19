import dataclasses
import json
import functools
from pathlib import Path

import pytest

from clipping import archiving, run
from clipping.config import paths
from clipping.doctor import Check
from clipping.models import Moment, Stream
from clipping.run import archive_stream, out_dir, parse_args, parse_section, stream_from_url
from clipping.state import RunState
from clipping.storage import archive_file, clean_work

EXT = -1  # fake home device id: tmp_path then counts as "external"
STREAM = Stream(id="youtube:abc", url="https://www.youtube.com/watch?v=abc", platform="youtube",
                streamer="@Kai", title="GTA 6", duration=7200.0, is_live=False)


def _setup(tmp_path):
    p = dataclasses.replace(paths({"CLIP_ARCHIVE": str(tmp_path / "arch")}), work=tmp_path / "work")
    p.archive.mkdir(parents=True)
    work_dir = p.work / "s1"
    work_dir.mkdir(parents=True)
    (work_dir / "c.mp4").write_bytes(b"video")
    return p, work_dir, p.out / "2026-11-19" / "Kai__x"


def _archive():
    return functools.partial(archive_file, home_dev=EXT)


def _clean(tmp_path):
    return functools.partial(clean_work, home=tmp_path)


def test_cli_parses_section():
    args = parse_args(["https://x", "--section", "1:00:00-1:10:00", "--clips", "1", "--fast"])
    assert args.section == (3600.0, 4200.0)
    assert args.urls == ["https://x"] and args.clips == 1 and args.fast
    assert args.parallel == 2 and args.pick_parallel == 4 and args.layout == "auto"


def test_parse_section_accepts_seconds_and_mmss():
    assert parse_section("3600-4200") == (3600.0, 4200.0)
    assert parse_section("1:30-2:00") == (90.0, 120.0)


@pytest.mark.parametrize("bad", ["4200-3600", "abc", "10", "1:2:3:4-5"])
def test_parse_section_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_section(bad)


def test_cli_rejects_bad_section(capsys):
    with pytest.raises(SystemExit):
        parse_args(["--section", "9-1"])


def test_out_dir_name_is_fat32_safe(tmp_path):
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    s = Stream(id="1", url="u", platform="youtube", streamer="Kai", title="GTA 6: day 1?", duration=1.0,
               is_live=False)
    assert out_dir(p, s, "2026-11-19").name == "Kai__GTA 6 day 1"


def test_work_cleaned_after_archive(tmp_path):
    p, work_dir, dest_dir = _setup(tmp_path)
    archive_stream(work_dir, [work_dir / "c.mp4"], dest_dir, p, keep_work=False,
                   archive=_archive(), clean=_clean(tmp_path))
    assert (dest_dir / "c.mp4").exists()
    assert not work_dir.exists()


def test_work_kept_when_archive_fails(tmp_path):
    p, work_dir, dest_dir = _setup(tmp_path)

    def boom(*a, **k):
        raise IOError("stick removed")

    with pytest.raises(IOError):
        archive_stream(work_dir, [work_dir / "c.mp4"], dest_dir, p, keep_work=False,
                       archive=boom, clean=_clean(tmp_path))
    assert (work_dir / "c.mp4").exists()


def test_keep_work_flag_skips_cleanup(tmp_path):
    p, work_dir, dest_dir = _setup(tmp_path)
    archive_stream(work_dir, [work_dir / "c.mp4"], dest_dir, p, keep_work=True,
                   archive=_archive(), clean=_clean(tmp_path))
    assert (dest_dir / "c.mp4").exists()
    assert work_dir.exists()


def test_archive_resumes_from_manifest_without_recopying(tmp_path):
    p, work_dir, dest_dir = _setup(tmp_path)
    (work_dir / "d.md").write_text("post")
    copied = []

    def flaky(src, dest, root):
        if src.name == "d.md" and "fail" not in copied:
            copied.append("fail")
            raise IOError("stick removed")
        copied.append(src.name)
        return _archive()(src, dest, root)

    files = [work_dir / "c.mp4", work_dir / "d.md"]
    with pytest.raises(IOError):
        archive_stream(work_dir, files, dest_dir, p, keep_work=False, archive=flaky, clean=_clean(tmp_path))
    assert archiving.read_manifest(work_dir) == ("c.mp4",) and work_dir.exists()
    out = archive_stream(work_dir, files, dest_dir, p, keep_work=False, archive=flaky, clean=_clean(tmp_path))
    assert copied == ["c.mp4", "fail", "d.md"]  # c.mp4 not copied again
    assert out == [(dest_dir / "c.mp4").resolve(), (dest_dir / "d.md").resolve()]
    assert not work_dir.exists()


def test_before_clean_failure_keeps_work(tmp_path):
    p, work_dir, dest_dir = _setup(tmp_path)

    def fail_save():
        raise OSError("state not saved")

    with pytest.raises(OSError):
        archive_stream(work_dir, [work_dir / "c.mp4"], dest_dir, p, keep_work=False, archive=_archive(),
                       clean=_clean(tmp_path), before_clean=fail_save)
    assert (work_dir / "c.mp4").exists()


def test_next_clip_number_continues_after_existing_clips(tmp_path):
    root = tmp_path / "arch"
    dest = root / "d"
    assert archiving.next_clip_number(dest, root) == 1
    dest.mkdir(parents=True)
    for name in ("01.mp4", "03.mp4", "POST_120000.md", "x04.mp4"):
        (dest / name).write_bytes(b"")
    assert archiving.next_clip_number(dest, root) == 4


def test_stream_from_url_youtube():
    info = {"id": "abc", "extractor_key": "Youtube", "uploader_id": "@KaiCenatLive", "title": "GTA 6",
            "duration": 7200, "live_status": "was_live"}
    s = stream_from_url("u", None, info=lambda url, cookies: info)
    assert s == Stream(id="youtube:abc", url="u", platform="youtube", streamer="@KaiCenatLive",
                       title="GTA 6", duration=7200, is_live=False)


def test_stream_from_url_twitch_live_estimates_duration():
    info = {"id": "v1", "extractor_key": "TwitchStream", "uploader_id": "kai", "uploader": "Kai Cenat",
            "title": "t", "live_status": "is_live", "release_timestamp": 1000}
    s = stream_from_url("u", None, info=lambda url, cookies: info, now=lambda: 4600.0)
    assert (s.id, s.platform, s.streamer, s.is_live, s.duration) == ("twitch:v1", "twitch", "@KaiCenat",
                                                                     True, 3600.0)


def test_stream_from_url_rejects_unknown_platform():
    with pytest.raises(ValueError):
        stream_from_url("u", None, info=lambda url, cookies: {"id": "x", "extractor_key": "Vimeo"})


def test_choose_section():
    assert run.choose_section(STREAM, RunState(), (10.0, 20.0)) == ((10.0, 20.0), 20.0)
    live = dataclasses.replace(STREAM, is_live=True)
    assert run.choose_section(live, RunState(processed_until=3600), None) == ((3510, 7200.0), 7200.0)
    assert run.choose_section(live, RunState(processed_until=7200), None) is None


def test_vod_without_section_is_processed_whole_every_time():
    assert run.choose_section(STREAM, RunState(), None) == (None, 7200.0)
    assert run.choose_section(STREAM, RunState(processed_until=7200), None) == (None, 7200.0)


def test_unknown_duration_is_processed_whole_and_marked_done():
    for live in (False, True):
        s = dataclasses.replace(STREAM, duration=None, is_live=live)
        assert run.choose_section(s, RunState(), None) == (None, run.WHOLE_STREAM_DONE)


def _ok_checks():
    return [Check("x", True, "")]


def _resolve(url, cookies):
    return dataclasses.replace(STREAM, id=f"youtube:{url}", url=url)


def test_main_stops_when_doctor_fails(capsys):
    called = []
    code = run.main(["u"], doctor_checks=lambda: [Check("archive", False, "plug the stick")],
                    process=lambda *a: called.append(a), resolve=_resolve)
    assert code == 1 and not called
    assert "plug the stick" in capsys.readouterr().out


def test_main_processes_every_url_and_reports_failures(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIP_ARCHIVE", str(tmp_path))
    seen = []

    def process(stream, opts, p, day):
        seen.append(stream.url)
        if stream.url == "bad":
            raise RuntimeError("download failed")
        return []

    code = run.main(["good", "bad", "--parallel", "1"], doctor_checks=_ok_checks, process=process,
                    resolve=_resolve)
    assert code == 1 and sorted(seen) == ["bad", "good"]
    assert "download failed" in capsys.readouterr().out


def test_main_dedupes_streams_by_id_and_reports_unresolvable(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIP_ARCHIVE", str(tmp_path))
    seen = []

    def resolve(url, cookies):
        if url == "broken":
            raise RuntimeError("yt-dlp failed")
        return STREAM  # both links are the same stream

    code = run.main(["https://youtu.be/abc", "https://www.youtube.com/watch?v=abc", "broken"],
                    doctor_checks=_ok_checks, resolve=resolve,
                    process=lambda stream, *a: seen.append(stream.id) or [])
    assert seen == [STREAM.id] and code == 1
    assert "yt-dlp failed" in capsys.readouterr().out


def test_main_list_prints_found_streams(capsys):
    code = run.main(["--list", "--streams", "1"], doctor_checks=_ok_checks,
                    finder=lambda n, cookies: [STREAM][:n],
                    process=lambda *a: pytest.fail("must not process"))
    assert code == 0 and STREAM.url in capsys.readouterr().out


def test_main_without_urls_finds_streams(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIP_ARCHIVE", str(tmp_path))
    seen = []
    code = run.main([], doctor_checks=_ok_checks, finder=lambda n, cookies: [STREAM],
                    process=lambda stream, *a: seen.append(stream.url) or [], resolve=_resolve)
    assert code == 0 and seen == [STREAM.url]


def test_usage_warning_printed_when_stick_full(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIP_ARCHIVE", str(tmp_path))
    monkeypatch.setattr(run.shutil, "disk_usage", lambda path: (100, 90, 10))
    run.main(["u"], doctor_checks=_ok_checks, process=lambda *a: [], resolve=_resolve)
    assert "90%" in capsys.readouterr().out


def _moment(start, score=50):
    return Moment(start=start, end=start + 30, score=score, category="funny", event="other", hook="h",
                  caption="c", hashtags=("#gta6",), reason="r")


def _fake_clip_stage(stream, work, nn, m, opts):
    out = work / "out" / f"{nn}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(f"clip {m.start}".encode())
    return m, out, {"render": 1.0}


def _fake_stages(monkeypatch, picks):
    monkeypatch.setattr(run.stages, "listen_stage", lambda stream, work, section, opts: ([], [], []))
    monkeypatch.setattr(run.stages, "pick_stage", lambda stream, work, heard, opts: picks.pop(0))
    monkeypatch.setattr(run.stages, "look_stage", lambda stream, work, cands, opts, p: cands)
    monkeypatch.setattr(run.stages, "clip_stage", _fake_clip_stage)


def _tmp_paths(tmp_path):
    p = dataclasses.replace(paths({"CLIP_ARCHIVE": str(tmp_path / "arch")}), work=tmp_path / "work")
    p.archive.mkdir()
    return p


def test_process_stream_wires_stages_archives_and_saves_state(tmp_path, monkeypatch):
    p = _tmp_paths(tmp_path)
    calls = {}
    _fake_stages(monkeypatch, [[_moment(100), _moment(500)]])
    monkeypatch.setattr(run.stages, "look_stage",
                        lambda stream, work, cands, opts, p: calls.setdefault("look", cands))
    monkeypatch.setattr(archiving, "datetime", _clock(["140501"]))

    def fake_archive(work_dir, files, dest, pp, keep, before_clean):
        calls["archived"] = [f.name for f in files]
        before_clean()

    monkeypatch.setattr(run, "archive_stream", fake_archive)
    monkeypatch.setattr(run.state, "load", lambda path: RunState(clipped=((100.0, 130.0),)))
    saved = []
    monkeypatch.setattr(run.state, "save", lambda path, s, root: saved.append(s))
    run.process_stream(STREAM, run.stages.Options(clips=1), p, "2026-11-19")
    assert calls["look"] == [_moment(500)]  # already-clipped moment filtered before the visual check
    assert calls["archived"] == ["01.mp4", "POST_140501.md", "clips_140501.json", "report_140501.json"]
    assert saved[0].processed_until == 7200.0 and (500, 530) in saved[0].clipped


def _clock(stamps):
    import datetime as dt

    class Clock:
        @staticmethod
        def now():
            return dt.datetime.strptime(stamps.pop(0), "%H%M%S")

    return Clock


def _real_stick(monkeypatch, tmp_path):
    real_save = run.state.save
    monkeypatch.setattr(archiving.storage, "archive_file", _archive())
    monkeypatch.setattr(archiving.storage, "clean_work", _clean(tmp_path))
    monkeypatch.setattr(run.state, "save", lambda path, s, root: real_save(path, s, root, home_dev=EXT))


def test_two_runs_same_day_do_not_collide(tmp_path, monkeypatch):
    p = _tmp_paths(tmp_path)
    _real_stick(monkeypatch, tmp_path)
    _fake_stages(monkeypatch, [[_moment(100)], [_moment(100), _moment(500)]])
    monkeypatch.setattr(archiving, "datetime", _clock(["120000", "150000"]))
    first = run.process_stream(STREAM, run.stages.Options(), p, "2026-11-19")
    second = run.process_stream(STREAM, run.stages.Options(), p, "2026-11-19")
    dest = out_dir(p, STREAM, "2026-11-19")
    assert sorted(f.name for f in dest.iterdir()) == [
        "01.mp4", "02.mp4", "POST_120000.md", "POST_150000.md", "clips_120000.json", "clips_150000.json",
        "report_120000.json", "report_150000.json"]
    assert (dest / "01.mp4").read_bytes() == b"clip 100" and (dest / "02.mp4").read_bytes() == b"clip 500"
    assert len(first) == 4 and len(second) == 4
    assert not (p.work / "youtubeabc").exists()


def test_state_save_failure_keeps_work_folder(tmp_path, monkeypatch):
    p = _tmp_paths(tmp_path)
    _real_stick(monkeypatch, tmp_path)
    _fake_stages(monkeypatch, [[_moment(100)]])

    def broken_save(path, s, root):
        raise OSError("stick full")

    monkeypatch.setattr(run.state, "save", broken_save)
    with pytest.raises(OSError):
        run.process_stream(STREAM, run.stages.Options(), p, "2026-11-19")
    assert (p.work / "youtubeabc" / "out" / "01.mp4").exists()


def test_process_stream_resume_keeps_numbering_and_stamp(tmp_path, monkeypatch):
    p = _tmp_paths(tmp_path)
    _real_stick(monkeypatch, tmp_path)
    _fake_stages(monkeypatch, [[_moment(100)], [_moment(100)]])
    monkeypatch.setattr(archiving, "datetime", _clock(["120000"]))  # a second stamp would raise
    real_archive = archiving.storage.archive_file
    calls = []

    def flaky(src, dest, root):
        calls.append(src.name)
        if len(calls) == 2:
            raise IOError("stick removed")
        return real_archive(src, dest, root)

    monkeypatch.setattr(archiving.storage, "archive_file", flaky)
    with pytest.raises(IOError):
        run.process_stream(STREAM, run.stages.Options(), p, "2026-11-19")
    run.process_stream(STREAM, run.stages.Options(), p, "2026-11-20")  # resumed after midnight
    dest = out_dir(p, STREAM, "2026-11-19")
    assert sorted(f.name for f in dest.iterdir()) == ["01.mp4", "POST_120000.md", "clips_120000.json",
                                                      "report_120000.json"]
    assert calls.count("01.mp4") == 1


def test_process_stream_skips_when_nothing_new(tmp_path, monkeypatch, capsys):
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    monkeypatch.setattr(run.state, "load", lambda path: RunState(processed_until=7200))
    live = dataclasses.replace(STREAM, is_live=True)
    assert run.process_stream(live, run.stages.Options(), p, "d") == []
    assert "nothing new" in capsys.readouterr().out


def test_process_stream_without_clips_saves_state_then_cleans_work(tmp_path, monkeypatch):
    p = dataclasses.replace(paths({"CLIP_ARCHIVE": str(tmp_path / "arch")}), work=tmp_path / "work")
    _fake_stages(monkeypatch, [[]])
    monkeypatch.setattr(run.state, "load", lambda path: RunState())
    events = []
    monkeypatch.setattr(run.state, "save", lambda path, s, root: events.append(("save", s.processed_until)))
    monkeypatch.setattr(run.storage, "clean_work", lambda work_dir, root: events.append(("clean", work_dir)))
    assert run.process_stream(STREAM, run.stages.Options(), p, "d") == []
    assert events == [("save", 7200.0), ("clean", p.work / "youtubeabc")]


def test_process_stream_redoes_stages_when_section_changed(tmp_path, monkeypatch):
    p = dataclasses.replace(paths({"CLIP_ARCHIVE": str(tmp_path / "arch")}), work=tmp_path / "work")
    monkeypatch.setattr(run.state, "load", lambda path: RunState())
    monkeypatch.setattr(run.stages, "cached_section_differs", lambda work, section: True)
    seen = []
    monkeypatch.setattr(run.stages, "listen_stage", lambda stream, work, section, opts: seen.append(opts.redo))
    monkeypatch.setattr(run.stages, "pick_stage", lambda *a: [])
    monkeypatch.setattr(run.stages, "look_stage", lambda *a: [])
    monkeypatch.setattr(run.state, "save", lambda *a: None)
    run.process_stream(STREAM, run.stages.Options(keep_work=True), p, "d")
    assert seen == [True]


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
