"""Environment checks. CLI: python -m clipping.doctor (exit 1 on any failure)."""
import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from clipping import config

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
FFMPEG_FIX = "brew install ffmpeg-full  (the build must include the ass filter)"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    fix: str


def check_ffmpeg(filters_output: str) -> Check:
    has_ass = any(
        len(line.split()) > 1 and line.split()[1] == "ass"
        for line in filters_output.splitlines()
    )
    return Check("ffmpeg ass filter", has_ass, "" if has_ass else FFMPEG_FIX)


def check_disk(free_bytes: int, need_bytes: int = config.MIN_MAC_FREE_BYTES) -> Check:
    ok = free_bytes >= need_bytes
    fix = "" if ok else f"Free space on the Mac: need {need_bytes // 10**9} GB, have {free_bytes / 10**9:.1f} GB"
    return Check("mac disk", ok, fix)


def _filters_output() -> str:
    try:
        proc = subprocess.run(
            [config.ffmpeg_bin(), "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=30,
        )
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _check_binary(name: str, fix: str) -> Check:
    found = shutil.which(name) is not None
    return Check(name, found, "" if found else fix)


def _check_module(module: str, pip_name: str) -> Check:
    found = importlib.util.find_spec(module) is not None
    fix = "" if found else f"Run skills/gta6-clipping/scripts/setup.sh (missing {pip_name})"
    return Check(f"python:{pip_name}", found, fix)


def _check_yunet() -> Check:
    present = (config.paths().models / YUNET_FILE).exists()
    fix = "" if present else "Run skills/gta6-clipping/scripts/setup.sh (downloads the YuNet model)"
    return Check("yunet model", present, fix)


def run_all() -> list:
    from clipping import storage  # lazy: storage imports Check from this module

    p = config.paths()
    ffprobe = Path(config.ffmpeg_bin()).with_name("ffprobe")
    ffprobe_ok = ffprobe.exists() or shutil.which("ffprobe") is not None
    return [
        check_ffmpeg(_filters_output()),
        Check("ffprobe", ffprobe_ok, "" if ffprobe_ok else "brew install ffmpeg-full"),
        _check_binary("node", "brew install node"),
        _check_module("yt_dlp", "yt-dlp"),
        _check_module("faster_whisper", "faster-whisper"),
        _check_binary("claude", "Install the Claude Code CLI"),
        _check_yunet(),
        *storage.preflight(
            p, shutil.disk_usage(Path.home()).free, storage.free_bytes(p.archive)
        ),
    ]


def main() -> int:
    checks = run_all()
    for c in checks:
        print(f"[{'ok' if c.ok else 'FAIL'}] {c.name}" + (f" -> {c.fix}" if not c.ok else ""))
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
