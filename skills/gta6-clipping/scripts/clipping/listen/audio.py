"""Audio-only download (never video) via yt-dlp."""
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .. import ytdlp
from ..models import Stream

DOWNLOAD_TIMEOUT_S = 3600


def download(stream: Stream, section: Optional[Tuple[float, float]], dest: Path,
             cookies: Optional[str] = None) -> Path:
    """Download best audio to `dest` (optionally only [start, end] seconds). Raises RuntimeError."""
    cmd = ytdlp.base_args(cookies) + ["-f", "bestaudio", "--no-playlist", "-o", str(dest), "--force-overwrites"]
    if section is not None:
        cmd += ["--download-sections", f"*{section[0]:.2f}-{section[1]:.2f}"]
    cmd.append(stream.url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"audio download timed out for {stream.url}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"audio download failed for {stream.url}: {proc.stderr.strip()[-300:]}")
    if not dest.exists():
        raise RuntimeError(f"audio download produced no file at {dest}")
    return dest
