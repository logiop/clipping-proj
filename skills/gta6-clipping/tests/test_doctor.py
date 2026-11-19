from clipping import doctor
from clipping.doctor import check_disk, check_ffmpeg


def test_reports_missing_ass_filter():
    c = check_ffmpeg(" ... drawtext ... subtitles ...")
    assert not c.ok and "brew install ffmpeg-full" in c.fix


def test_accepts_ffmpeg_with_ass():
    assert check_ffmpeg(" T.. ass               V->V       Render ASS subtitles").ok


def test_low_disk_fails():
    assert not check_disk(free_bytes=1_000_000_000).ok


def test_enough_disk_passes():
    assert check_disk(free_bytes=10_000_000_000).ok


def test_run_all_reports_every_tool_check(monkeypatch, tmp_path):
    from clipping import doctor

    real_paths = doctor.config.paths
    monkeypatch.setattr(doctor.config, "paths", lambda: real_paths({"CLIP_ARCHIVE": str(tmp_path)}))

    monkeypatch.setattr(doctor, "_filters_output", lambda: " T.. ass  V->V  x")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(doctor, "_check_yunet", lambda: doctor.Check("yunet model", True, ""))
    checks = doctor.run_all()
    names = {c.name for c in checks}
    assert {"ffmpeg ass filter", "node", "claude", "yunet model", "mac disk", "archive"} <= names


def test_main_exits_1_and_prints_fix_on_failure(monkeypatch, capsys):
    from clipping import doctor

    monkeypatch.setattr(doctor, "run_all", lambda: [doctor.Check("x", False, "do the fix")])
    assert doctor.main() == 1
    assert "do the fix" in capsys.readouterr().out


def test_main_exits_0_when_all_ok(monkeypatch):
    from clipping import doctor

    monkeypatch.setattr(doctor, "run_all", lambda: [doctor.Check("x", True, "")])
    assert doctor.main() == 0


def test_missing_module_and_binary_report_fix(monkeypatch):
    from clipping import doctor

    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert not doctor._check_module("yt_dlp", "yt-dlp").ok
    assert "brew install node" in doctor._check_binary("node", "brew install node").fix


def test_yunet_missing_when_models_dir_empty(monkeypatch, tmp_path):
    from clipping import doctor

    real_paths = doctor.config.paths
    monkeypatch.setattr(doctor.config, "paths", lambda: real_paths({"HOME": str(tmp_path)}))
    assert not doctor._check_yunet().ok


def test_filters_output_is_empty_when_ffmpeg_missing(monkeypatch):
    from clipping import doctor

    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(doctor.subprocess, "run", boom)
    assert doctor._filters_output() == ""


def test_fix_messages_point_to_the_installed_setup_script(monkeypatch):
    from pathlib import Path
    expected = Path(doctor.__file__).resolve().parents[1] / "setup.sh"
    assert doctor.SETUP_SH == expected and expected.exists()
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: None)
    assert str(expected) in doctor._check_module("yt_dlp", "yt-dlp").fix
    real_paths = doctor.config.paths
    monkeypatch.setattr(doctor.config, "paths", lambda: real_paths({"HOME": "/nonexistent"}))
    assert str(expected) in doctor._check_yunet().fix
