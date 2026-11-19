"""Safety layer for the USB archive. Every archive write goes through safe_path;
every delete goes through clean_work (Mac work root only)."""
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

from clipping import config
from clipping.config import Paths
from clipping.doctor import Check

FAT32_MAX_BYTES = config.FAT32_MAX_FILE_BYTES
DEFAULT_NAME_MAX = 100
GB = 10**9
VOLUMES_ROOT = Path("/Volumes")
STICK_MISSING_FIX = "Chiavetta non trovata: collega KINGSTOM e riprova"

_ILLEGAL_CHARS = re.compile(r'[:?"*<>|/\\\x00-\x1f\x7f]')
_SPACES = re.compile(r"\s+")


class UnsafePathError(Exception):
    """A path resolves outside the root it must stay in."""


def safe_path(root: Path, p: Path) -> Path:
    resolved_root = Path(root).resolve()
    resolved = Path(p).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise UnsafePathError(f"{resolved} is outside {resolved_root}")
    return resolved


def safe_name(s: str, max_len: int = DEFAULT_NAME_MAX) -> str:
    cleaned = _SPACES.sub(" ", _ILLEGAL_CHARS.sub("", s))
    cleaned = cleaned.strip(". ")[:max_len].strip(". ")
    return cleaned or "untitled"


def free_bytes(path: Path) -> Optional[int]:
    path = Path(path)
    if not path.exists():
        return None
    return shutil.disk_usage(path).free


def usage_warning(total: int, free: int, threshold: float = 0.8) -> Optional[str]:
    if total <= 0:
        return None
    used = (total - free) / total
    if used <= threshold:
        return None
    return f"Chiavetta piena al {used:.0%}: fai pulizia in Cartella di Claude"


def _home_dev(home_dev: Optional[int]) -> int:
    return home_dev if home_dev is not None else os.stat(Path.home()).st_dev


def on_external_volume(root: Path, home_dev: Optional[int] = None) -> bool:
    """True only when root exists and lives on a different device than the Mac home."""
    root = Path(root)
    return root.is_dir() and os.stat(root).st_dev != _home_dev(home_dev)


def preflight(
    p: Paths, mac_free: int, stick_free: Optional[int], *, home_dev: Optional[int] = None
) -> List[Check]:
    settings = config.load()
    mac_ok = mac_free >= settings.min_mac_free_bytes
    mac = Check(
        "mac disk",
        mac_ok,
        "" if mac_ok else f"Spazio sul Mac sotto {settings.min_mac_free_bytes // GB} GB: libera spazio",
    )
    if stick_free is None or not on_external_volume(p.archive, home_dev):
        return [mac, Check("archive", False, STICK_MISSING_FIX)]
    stick_ok = stick_free >= settings.min_stick_free_bytes
    stick_gb = settings.min_stick_free_bytes // GB
    stick = Check(
        "stick space",
        stick_ok,
        "" if stick_ok else f"Chiavetta quasi piena (sotto {stick_gb} GB): fai pulizia in Cartella di Claude",
    )
    return [mac, Check("archive", True, ""), stick]


def _copy_verified(src: Path, target: Path, root: Path, size: int) -> None:
    part = safe_path(root, target.with_name(target.name + ".part"))
    try:
        shutil.copyfile(src, part)
        if part.stat().st_size != size:
            raise IOError(f"Copy of {src.name} to the archive is incomplete")
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def archive_file(
    src: Path,
    dest: Path,
    root: Path,
    max_bytes: int = FAT32_MAX_BYTES,
    *,
    home_dev: Optional[int] = None,
) -> Path:
    src, root = Path(src), Path(root)
    size = src.stat().st_size
    if size > max_bytes:
        raise ValueError(f"{src.name} is {size} bytes, over the {max_bytes} byte limit")
    if not on_external_volume(root, home_dev):
        raise FileNotFoundError(f"Archive root missing or not on an external volume: {root}")
    target = safe_path(root, dest)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _copy_verified(src, target, root, size)
    return target


def clean_work(
    work_dir: Path,
    work_root: Path,
    *,
    home: Path = Path.home(),
    volumes: Path = VOLUMES_ROOT,
) -> None:
    resolved_root = Path(work_root).resolve()
    resolved_volumes = Path(volumes).resolve()
    if resolved_root == resolved_volumes or resolved_volumes in resolved_root.parents:
        raise UnsafePathError(f"Work root {resolved_root} is on a volume")
    if Path(home).resolve() not in resolved_root.parents:
        raise UnsafePathError(f"Work root {resolved_root} is not under the home folder")
    target = safe_path(work_root, work_dir)
    if target == resolved_root:
        raise UnsafePathError("Refusing to delete the work root itself")
    shutil.rmtree(target)
