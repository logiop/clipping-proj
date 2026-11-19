from pathlib import Path

from clipping.config import load, paths


def test_load_overrides_do_not_mutate_defaults():
    a = load({"clips_per_stream": 5})
    b = load()
    assert a.clips_per_stream == 5 and b.clips_per_stream == 3


def test_paths_default_archive_is_cartella_di_claude():
    p = paths({})
    assert p.archive == Path("/Volumes/KINGSTOM/Cartella di Claude")
    assert p.out == p.archive / "gta6-clips" and p.hf_home == p.archive / "models"
    assert p.state == p.out / "state"
    assert not str(p.work).startswith("/Volumes")


def test_paths_env_override(tmp_path):
    assert paths({"CLIP_ARCHIVE": str(tmp_path)}).archive == tmp_path


def test_ffmpeg_bin_prefers_full_build(monkeypatch):
    from clipping import config

    monkeypatch.setattr(config.Path, "exists", lambda self: True)
    assert config.ffmpeg_bin() == config.FFMPEG_FULL


def test_ffmpeg_bin_falls_back_to_path(monkeypatch):
    from clipping import config

    monkeypatch.setattr(config.Path, "exists", lambda self: False)
    monkeypatch.setattr(config.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert config.ffmpeg_bin() == "/usr/bin/ffmpeg"


def test_paths_none_reads_process_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIP_ARCHIVE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    p = paths(None)
    assert p.archive == tmp_path and p.home == tmp_path / "h"
    assert paths({}).archive == Path("/Volumes/KINGSTOM/Cartella di Claude")


def test_free_space_thresholds_are_single_source():
    from clipping import config

    s = load()
    assert s.min_mac_free_bytes == config.MIN_MAC_FREE_BYTES == 5_000_000_000
    assert s.min_stick_free_bytes == config.MIN_STICK_FREE_BYTES == 2_000_000_000
