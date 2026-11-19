"""Download only the candidate minutes: a 360p preview for frames, then the 1080p clip."""
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from . import config, ytdlp
from .models import Moment, Stream

DEFAULT_PAD_S = 2.0
DOWNLOAD_TIMEOUT_S = 1800
FFMPEG_TIMEOUT_S = 120
CLIP_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]"
PREVIEW_FORMAT = "bv*[height<=360]"


def clip_section(m: Moment, pad: float = DEFAULT_PAD_S) -> Tuple[float, float]:
    """Moment window padded on both sides, never before 0."""
    return max(0.0, m.start - pad), m.end + pad


def _download(stream: Stream, m: Moment, dest: Path, cookies: Optional[str], fmt: str,
              name: str, extra: Sequence[str], runner: Callable) -> Path:
    start, end = clip_section(m)
    out = dest / name
    cmd = ytdlp.base_args(cookies) + [
        "-f", fmt, "--no-playlist", "--force-overwrites", "-o", str(out),
        "--ffmpeg-location", str(Path(config.ffmpeg_bin()).parent),
        "--download-sections", f"*{start:.2f}-{end:.2f}", *extra, stream.url]
    dest.mkdir(parents=True, exist_ok=True)
    try:
        proc = runner(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"video download timed out for {stream.url}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"video download failed for {stream.url}: {proc.stderr.strip()[-300:]}")
    if not out.exists():
        raise RuntimeError(f"video download produced no file at {out}")
    return out


def _stem(m: Moment) -> str:
    return f"{m.start:.0f}-{m.end:.0f}"


def download_preview(stream: Stream, m: Moment, dest: Path, cookies: Optional[str],
                     runner: Callable = subprocess.run) -> Path:
    """Low-res (<=360p) copy of the candidate window, used only to grab frames."""
    return _download(stream, m, dest, cookies, PREVIEW_FORMAT, f"preview_{_stem(m)}.mp4", (), runner)


def download_clip(stream: Stream, m: Moment, dest: Path, cookies: Optional[str],
                  runner: Callable = subprocess.run) -> Path:
    """1080p copy of the padded candidate window. Raises RuntimeError."""
    return _download(stream, m, dest, cookies, CLIP_FORMAT, f"clip_{_stem(m)}.mp4",
                     ("--force-keyframes-at-cuts",), runner)


def extract_frames(preview: Path, offsets: Sequence[float], out_dir: Path, tag: str,
                   runner: Callable = subprocess.run) -> List[Path]:
    """One JPEG per offset (seconds into the preview), named `<tag>_t<offset>.jpg`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for off in offsets:
        out = out_dir / f"{tag}_t{off:.0f}.jpg"
        cmd = [config.ffmpeg_bin(), "-y", "-loglevel", "error", "-ss", f"{off:.2f}", "-i", str(preview),
               "-frames:v", "1", "-q:v", "3", str(out)]
        try:
            proc = runner(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"frame extraction timed out for {preview}") from exc
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"frame extraction failed for {preview}: {proc.stderr.strip()[-300:]}")
        frames.append(out)
    return frames
