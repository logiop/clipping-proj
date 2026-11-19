import dataclasses
import functools
from pathlib import Path

import pytest

from clipping import run
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


def test_archive_resume_skips_identical_archived_file(tmp_path):
    p, work_dir, dest_dir = _setup(tmp_path)
    dest_dir.mkdir(parents=True)
    (dest_dir / "c.mp4").write_bytes(b"video")
    out = archive_stream(work_dir, [work_dir / "c.mp4"], dest_dir, p, keep_work=False,
                         archive=_archive(), clean=_clean(tmp_path))
    assert out == [(dest_dir / "c.mp4").resolve()]
    assert not work_dir.exists()


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
    assert run.choose_section(STREAM, RunState(), None) == (None, 7200.0)
    assert run.choose_section(STREAM, RunState(processed_until=7200), None) is None
    live = dataclasses.replace(STREAM, is_live=True)
    assert run.choose_section(live, RunState(processed_until=3600), None) == ((3510, 7200.0), 7200.0)
    assert run.choose_section(live, RunState(processed_until=7200), None) is None


def _ok_checks():
    return [Check("x", True, "")]


def test_main_stops_when_doctor_fails(capsys):
    called = []
    code = run.main(["u"], doctor_checks=lambda: [Check("archive", False, "plug the stick")],
                    process=lambda *a: called.append(a))
    assert code == 1 and not called
    assert "plug the stick" in capsys.readouterr().out


def test_main_processes_every_url_and_reports_failures(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIP_ARCHIVE", str(tmp_path))
    seen = []

    def process(url, opts, p, day):
        seen.append(url)
        if url == "bad":
            raise RuntimeError("download failed")
        return []

    code = run.main(["good", "bad", "--parallel", "1"], doctor_checks=_ok_checks, process=process)
    assert code == 1 and sorted(seen) == ["bad", "good"]
    assert "download failed" in capsys.readouterr().out


def test_main_list_prints_found_streams(capsys):
    code = run.main(["--list", "--streams", "1"], doctor_checks=_ok_checks,
                    finder=lambda n, cookies: [STREAM][:n],
                    process=lambda *a: pytest.fail("must not process"))
    assert code == 0 and STREAM.url in capsys.readouterr().out


def test_main_without_urls_finds_streams(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIP_ARCHIVE", str(tmp_path))
    seen = []
    code = run.main([], doctor_checks=_ok_checks, finder=lambda n, cookies: [STREAM],
                    process=lambda url, *a: seen.append(url) or [])
    assert code == 0 and seen == [STREAM.url]


def test_usage_warning_printed_when_stick_full(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIP_ARCHIVE", str(tmp_path))
    monkeypatch.setattr(run.shutil, "disk_usage", lambda path: (100, 90, 10))
    run.main(["u"], doctor_checks=_ok_checks, process=lambda *a: [])
    assert "90%" in capsys.readouterr().out


def _moment(start, score=50):
    return Moment(start=start, end=start + 30, score=score, category="funny", event="other", hook="h",
                  caption="c", hashtags=("#gta6",), reason="r")


def test_process_stream_wires_stages_archives_and_saves_state(tmp_path, monkeypatch):
    p = dataclasses.replace(paths({"CLIP_ARCHIVE": str(tmp_path / "arch")}), work=tmp_path / "work")
    p.archive.mkdir()
    calls = {}
    monkeypatch.setattr(run, "stream_from_url", lambda url, cookies: STREAM)
    monkeypatch.setattr(run.stages, "listen_stage", lambda stream, work, section, opts: calls.setdefault(
        "listen", ([], [], [])))
    old = _moment(100)
    monkeypatch.setattr(run.stages, "pick_stage", lambda stream, work, heard, opts: [old, _moment(500)])
    monkeypatch.setattr(run.stages, "look_stage",
                        lambda stream, work, cands, opts, p: calls.setdefault("look", cands))

    def clip_stage(stream, work, nn, m, opts):
        out = work / "out" / f"{nn}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"v")
        return m, out, {"render": 1.0}

    monkeypatch.setattr(run.stages, "clip_stage", clip_stage)
    monkeypatch.setattr(run, "archive_stream", lambda work_dir, files, dest, pp, keep:
                        calls.setdefault("archived", [f.name for f in files]))
    monkeypatch.setattr(run.state, "load", lambda path: RunState(clipped=((100.0, 130.0),)))
    saved = []
    monkeypatch.setattr(run.state, "save", lambda path, s, root: saved.append(s))
    opts = run.stages.Options(clips=1)
    run.process_stream("u", opts, p, "2026-11-19")
    assert calls["look"] == [_moment(500)]  # already-clipped moment filtered before the visual check
    assert calls["archived"] == ["01.mp4", "POST.md", "clips.json", "report.json"]
    assert saved[0].processed_until == 7200.0 and (500, 530) in saved[0].clipped


def test_process_stream_skips_when_nothing_new(tmp_path, monkeypatch, capsys):
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    monkeypatch.setattr(run, "stream_from_url", lambda url, cookies: STREAM)
    monkeypatch.setattr(run.state, "load", lambda path: RunState(processed_until=7200))
    assert run.process_stream("u", run.stages.Options(), p, "d") == []
    assert "nothing new" in capsys.readouterr().out


def test_process_stream_without_clips_cleans_work_and_saves_state(tmp_path, monkeypatch):
    p = dataclasses.replace(paths({"CLIP_ARCHIVE": str(tmp_path / "arch")}), work=tmp_path / "work")
    monkeypatch.setattr(run, "stream_from_url", lambda url, cookies: STREAM)
    monkeypatch.setattr(run.stages, "listen_stage", lambda *a: ([], [], []))
    monkeypatch.setattr(run.stages, "pick_stage", lambda *a: [])
    monkeypatch.setattr(run.stages, "look_stage", lambda *a: [])
    monkeypatch.setattr(run.state, "load", lambda path: RunState())
    saved, cleaned = [], []
    monkeypatch.setattr(run.state, "save", lambda path, s, root: saved.append(s))
    monkeypatch.setattr(run.storage, "clean_work", lambda work_dir, root: cleaned.append(work_dir))
    assert run.process_stream("u", run.stages.Options(), p, "d") == []
    assert saved[0].processed_until == 7200.0 and cleaned == [p.work / "youtubeabc"]


def test_process_stream_redoes_stages_when_section_changed(tmp_path, monkeypatch):
    p = dataclasses.replace(paths({"CLIP_ARCHIVE": str(tmp_path / "arch")}), work=tmp_path / "work")
    monkeypatch.setattr(run, "stream_from_url", lambda url, cookies: STREAM)
    monkeypatch.setattr(run.state, "load", lambda path: RunState())
    monkeypatch.setattr(run.stages, "cached_section_differs", lambda work, section: True)
    seen = []
    monkeypatch.setattr(run.stages, "listen_stage", lambda stream, work, section, opts: seen.append(opts.redo))
    monkeypatch.setattr(run.stages, "pick_stage", lambda *a: [])
    monkeypatch.setattr(run.stages, "look_stage", lambda *a: [])
    monkeypatch.setattr(run.state, "save", lambda *a: None)
    monkeypatch.setattr(run.storage, "clean_work", lambda *a: None)
    run.process_stream("u", run.stages.Options(keep_work=True), p, "d")
    assert seen == [True]
