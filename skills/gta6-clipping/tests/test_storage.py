from pathlib import Path

import pytest

from clipping.config import paths
from clipping.storage import (
    UnsafePathError,
    archive_file,
    clean_work,
    free_bytes,
    preflight,
    safe_name,
    safe_path,
    usage_warning,
)


EXT = -1  # fake home device id: tmp_path then counts as "external"


def test_safe_path_rejects_parent_escape(tmp_path):
    root = tmp_path / "Cartella di Claude"; root.mkdir()
    (tmp_path / "foto video NON TOCCARE").mkdir()
    with pytest.raises(UnsafePathError):
        safe_path(root, root / ".." / "foto video NON TOCCARE" / "x.mp4")


def test_safe_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "a"; root.mkdir(); (tmp_path / "b").mkdir()
    (root / "link").symlink_to(tmp_path / "b")
    with pytest.raises(UnsafePathError):
        safe_path(root, root / "link" / "x")


def test_safe_path_accepts_root_and_children(tmp_path):
    root = tmp_path / "a"; root.mkdir()
    assert safe_path(root, root) == root.resolve()
    assert safe_path(root, root / "x" / "y.mp4") == (root / "x" / "y.mp4").resolve()


def test_safe_name_neutralises_traversal():
    assert "/" not in safe_name("../foto video NON TOCCARE") and not safe_name("..").startswith(".")


def test_safe_name_strips_fat32_chars():
    assert safe_name('Kai: GTA? "6" <live>|*') == "Kai GTA 6 live"


def test_safe_name_empty_becomes_untitled_and_is_truncated():
    assert safe_name("???") == "untitled"
    assert len(safe_name("a" * 300)) == 100


def test_archive_file_refuses_over_limit(tmp_path):
    src = tmp_path / "big.mp4"; src.write_bytes(b"x" * 11)
    with pytest.raises(ValueError):
        archive_file(src, tmp_path / "arch" / "big.mp4", tmp_path / "arch", max_bytes=10)
    assert not (tmp_path / "arch" / "big.mp4").exists()


def test_archive_file_copies_and_keeps_source(tmp_path):
    src = tmp_path / "c.mp4"; src.write_bytes(b"abc"); root = tmp_path / "arch"; root.mkdir()
    out = archive_file(src, root / "2026-11-19" / "c.mp4", root, home_dev=EXT)
    assert out.read_bytes() == b"abc" and src.exists()


def test_archive_file_refuses_dest_outside_root(tmp_path):
    src = tmp_path / "c.mp4"; src.write_bytes(b"abc"); root = tmp_path / "arch"; root.mkdir()
    with pytest.raises(UnsafePathError):
        archive_file(src, tmp_path / "elsewhere" / "c.mp4", root, home_dev=EXT)
    assert not (tmp_path / "elsewhere").exists()


def test_archive_file_never_creates_missing_root(tmp_path):
    src = tmp_path / "c.mp4"; src.write_bytes(b"abc")
    with pytest.raises(FileNotFoundError):
        archive_file(src, tmp_path / "KINGSTOM" / "arch" / "c.mp4", tmp_path / "KINGSTOM" / "arch", home_dev=EXT)
    assert not (tmp_path / "KINGSTOM").exists()


def test_archive_file_deletes_partial_copy_on_size_mismatch(tmp_path, monkeypatch):
    from clipping import storage

    src = tmp_path / "c.mp4"; src.write_bytes(b"abc"); root = tmp_path / "arch"; root.mkdir()
    monkeypatch.setattr(storage.shutil, "copyfile", lambda s, d: Path(d).write_bytes(b"a"))
    with pytest.raises(IOError):
        archive_file(src, root / "c.mp4", root, home_dev=EXT)
    assert not (root / "c.mp4").exists() and src.exists()


def test_preflight_missing_archive_does_not_create_it(tmp_path):
    p = paths({"CLIP_ARCHIVE": str(tmp_path / "KINGSTOM" / "Cartella di Claude")})
    checks = preflight(p, mac_free=50_000_000_000, stick_free=None)
    assert any(not c.ok and "chiavetta" in c.fix.lower() for c in checks)
    assert not (tmp_path / "KINGSTOM").exists()


def test_preflight_low_space(tmp_path):
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    assert not all(c.ok for c in preflight(p, mac_free=4_000_000_000, stick_free=10_000_000_000))
    assert not all(c.ok for c in preflight(p, mac_free=50_000_000_000, stick_free=1_000_000_000))


def test_preflight_all_ok(tmp_path):
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    assert all(c.ok for c in preflight(p, mac_free=50_000_000_000, stick_free=10_000_000_000, home_dev=EXT))


def test_usage_warning_over_80_percent():
    assert usage_warning(total=100, free=15) and usage_warning(total=100, free=30) is None


def test_usage_warning_ignores_unknown_total():
    assert usage_warning(total=0, free=0) is None


def test_free_bytes_none_for_missing_path(tmp_path):
    assert free_bytes(tmp_path / "nope") is None
    assert free_bytes(tmp_path) > 0


def test_clean_work_refuses_outside_work_root(tmp_path):
    work_root = tmp_path / "work"; (work_root / "s1").mkdir(parents=True); other = tmp_path / "photos"; other.mkdir()
    with pytest.raises(UnsafePathError):
        clean_work(other, work_root, home=tmp_path)
    with pytest.raises(UnsafePathError):
        clean_work(work_root, work_root, home=tmp_path)
    clean_work(work_root / "s1", work_root, home=tmp_path)
    assert other.exists() and not (work_root / "s1").exists()


def test_safe_path_rejects_sibling_with_same_prefix(tmp_path):
    root = tmp_path / "Cartella di Claude"; root.mkdir()
    with pytest.raises(UnsafePathError):
        safe_path(root, tmp_path / "Cartella di Claude2" / "x")


def test_safe_path_rejects_dotdot_after_missing_components(tmp_path):
    root = tmp_path / "a"; root.mkdir()
    with pytest.raises(UnsafePathError):
        safe_path(root, root / "nope" / ".." / ".." / "b" / "x")


def test_archive_file_copy_error_leaves_no_part_and_no_target(tmp_path, monkeypatch):
    from clipping import storage

    src = tmp_path / "c.mp4"; src.write_bytes(b"abc"); root = tmp_path / "arch"; root.mkdir()

    def boom(s, d):
        Path(d).write_bytes(b"a")
        raise OSError("ENOSPC")

    monkeypatch.setattr(storage.shutil, "copyfile", boom)
    with pytest.raises(OSError):
        archive_file(src, root / "c.mp4", root, home_dev=EXT)
    assert list(root.iterdir()) == []


def test_archive_file_refuses_existing_dest_untouched(tmp_path):
    src = tmp_path / "c.mp4"; src.write_bytes(b"new"); root = tmp_path / "arch"; root.mkdir()
    (root / "c.mp4").write_bytes(b"old")
    with pytest.raises(FileExistsError):
        archive_file(src, root / "c.mp4", root, home_dev=EXT)
    assert (root / "c.mp4").read_bytes() == b"old" and not (root / "c.mp4.part").exists()


def test_size_mismatch_keeps_preexisting_sibling_and_no_part(tmp_path, monkeypatch):
    from clipping import storage

    src = tmp_path / "c.mp4"; src.write_bytes(b"abc"); root = tmp_path / "arch"; root.mkdir()
    (root / "other.mp4").write_bytes(b"keep")
    monkeypatch.setattr(storage.shutil, "copyfile", lambda s, d: Path(d).write_bytes(b"a"))
    with pytest.raises(IOError):
        archive_file(src, root / "c.mp4", root, home_dev=EXT)
    assert sorted(x.name for x in root.iterdir()) == ["other.mp4"]


def test_archive_on_same_device_as_home_is_not_the_stick(tmp_path):
    import os

    home_dev = os.stat(tmp_path).st_dev
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    checks = preflight(p, mac_free=50_000_000_000, stick_free=10_000_000_000, home_dev=home_dev)
    assert any(not c.ok and "chiavetta" in c.fix.lower() for c in checks)
    src = tmp_path / "c.mp4"; src.write_bytes(b"abc")
    with pytest.raises(FileNotFoundError):
        archive_file(src, tmp_path / "arch" / "c.mp4", tmp_path / "arch", home_dev=home_dev)


def test_preflight_messages_use_settings_thresholds(tmp_path):
    p = paths({"CLIP_ARCHIVE": str(tmp_path)})
    fixes = " ".join(c.fix for c in preflight(p, 1, 1, home_dev=EXT))
    assert "5 GB" in fixes and "2 GB" in fixes


def test_clean_work_refuses_work_root_on_a_volume(tmp_path):
    volumes = tmp_path / "Volumes"; work_root = volumes / "KINGSTOM" / "work"; (work_root / "s1").mkdir(parents=True)
    with pytest.raises(UnsafePathError):
        clean_work(work_root / "s1", work_root, home=tmp_path, volumes=volumes)
    assert (work_root / "s1").exists()


def test_clean_work_refuses_work_root_outside_home(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    work_root = tmp_path / "elsewhere" / "work"; (work_root / "s1").mkdir(parents=True)
    with pytest.raises(UnsafePathError):
        clean_work(work_root / "s1", work_root, home=home, volumes=tmp_path / "Volumes")
    assert (work_root / "s1").exists()


def _mount_at(monkeypatch, root):
    from clipping import storage
    monkeypatch.setattr(storage.os.path, "ismount", lambda p: Path(p).resolve() == Path(root).resolve())


def test_archive_root_that_is_a_mount_point_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "stick"
    root.mkdir()
    _mount_at(monkeypatch, root)
    src = tmp_path / "c.mp4"
    src.write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="subfolder"):
        archive_file(src, root / "c.mp4", root, home_dev=EXT)
    assert not (root / "c.mp4").exists()
    checks = preflight(paths({"CLIP_ARCHIVE": str(root)}), 50_000_000_000, 10_000_000_000, home_dev=EXT)
    archive = next(c for c in checks if c.name == "archive")
    assert not archive.ok and "sottocartella" in archive.fix
