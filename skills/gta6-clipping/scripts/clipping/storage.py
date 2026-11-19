"""Safety layer for the USB archive. Every archive write goes through safe_path;
every delete goes through clean_work (Mac work root only)."""
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


def preflight(p: Paths, mac_free: int, stick_free: Optional[int]) -> List[Check]:
    settings = config.load()
    mac_ok = mac_free >= settings.min_mac_free_bytes
    mac = Check(
        "mac disk",
        mac_ok,
        "" if mac_ok else "Spazio sul Mac sotto 5 GB: libera spazio",
    )
    if stick_free is None:
        return [mac, Check("archive", False, "Chiavetta non trovata: collega KINGSTOM e riprova")]
    stick_ok = stick_free >= settings.min_stick_free_bytes
    stick = Check(
        "stick space",
        stick_ok,
        "" if stick_ok else "Chiavetta quasi piena (sotto 2 GB): fai pulizia in Cartella di Claude",
    )
    return [mac, Check("archive", True, ""), stick]


def archive_file(src: Path, dest: Path, root: Path, max_bytes: int = FAT32_MAX_BYTES) -> Path:
    src, root = Path(src), Path(root)
    size = src.stat().st_size
    if size > max_bytes:
        raise ValueError(f"{src.name} is {size} bytes, over the {max_bytes} byte limit")
    if not root.is_dir():
        raise FileNotFoundError(f"Archive root missing: {root}")
    target = safe_path(root, dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    if target.stat().st_size != size:
        target.unlink()
        raise IOError(f"Copy of {src.name} to the archive is incomplete")
    return target


def clean_work(work_dir: Path, work_root: Path) -> None:
    target = safe_path(work_root, work_dir)
    if target == Path(work_root).resolve():
        raise UnsafePathError("Refusing to delete the work root itself")
    shutil.rmtree(target)
