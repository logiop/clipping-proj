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
    out = archive_file(src, root / "2026-11-19" / "c.mp4", root)
    assert out.read_bytes() == b"abc" and src.exists()


def test_archive_file_refuses_dest_outside_root(tmp_path):
    src = tmp_path / "c.mp4"; src.write_bytes(b"abc"); root = tmp_path / "arch"; root.mkdir()
    with pytest.raises(UnsafePathError):
        archive_file(src, tmp_path / "elsewhere" / "c.mp4", root)
    assert not (tmp_path / "elsewhere").exists()


def test_archive_file_never_creates_missing_root(tmp_path):
    src = tmp_path / "c.mp4"; src.write_bytes(b"abc")
    with pytest.raises(FileNotFoundError):
        archive_file(src, tmp_path / "KINGSTOM" / "arch" / "c.mp4", tmp_path / "KINGSTOM" / "arch")
    assert not (tmp_path / "KINGSTOM").exists()


def test_archive_file_deletes_partial_copy_on_size_mismatch(tmp_path, monkeypatch):
    from clipping import storage

    src = tmp_path / "c.mp4"; src.write_bytes(b"abc"); root = tmp_path / "arch"; root.mkdir()
    monkeypatch.setattr(storage.shutil, "copyfile", lambda s, d: open(d, "wb").write(b"a"))
    with pytest.raises(IOError):
        archive_file(src, root / "c.mp4", root)
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
    assert all(c.ok for c in preflight(p, mac_free=50_000_000_000, stick_free=10_000_000_000))


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
        clean_work(other, work_root)
    with pytest.raises(UnsafePathError):
        clean_work(work_root, work_root)
    clean_work(work_root / "s1", work_root)
    assert other.exists() and not (work_root / "s1").exists()
