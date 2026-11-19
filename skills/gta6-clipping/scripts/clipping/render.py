"""Render: one ffmpeg command turns a 16:9 clip into the final 1080x1920 video."""
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List

from . import config
from .layout import CAM_OUT_H, OUT_H, OUT_W, LayoutPlan

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
HOOK_BAR_H = 150
HOOK_BAR_ALPHA = 0.95
HOOK_BAR_TOP_Y = 300
HOOK_TEXT_WIDTH_PX = 1000
HOOK_CHAR_WIDTH_EM = 0.65
HOOK_FONT_SIZES = (52, 44, 38, 32)
HOOK_MAX_LINES = 2
CREDIT_FONT_SIZE = 36
CREDIT_MARGIN = 40
DARK_LUMA = 60
BRIGHTNESS_LIFT = 0.06
FAST_VIDEO_BITRATE = "8M"
LUMA_SAMPLE_FRAMES = 5
NOT_DARK_LUMA = 128.0
FILTER_SPECIALS = set("\\':,;[] ")
STDERR_TAIL_CHARS = 1500


def font_path() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(f"no hook font found; tried: {', '.join(FONT_CANDIDATES)}")


def escape_filter_path(path) -> str:
    """Escape for both ffmpeg graph and filter-option parsing (two levels)."""
    out = []
    for ch in str(path):
        if ch == "\\":
            out.append("\\" * 4)
        elif ch == "'":
            out.append("\\" * 3 + ch)
        elif ch in FILTER_SPECIALS:
            out.append("\\" * 2 + ch)
        else:
            out.append(ch)
    return "".join(out)


def wrap_hook(hook: str):
    """Return (text with at most 2 lines, font size)."""
    hook = " ".join(hook.split())
    lines: List[str] = [hook]
    size = HOOK_FONT_SIZES[0]
    for size in HOOK_FONT_SIZES:
        width = int(HOOK_TEXT_WIDTH_PX / (HOOK_CHAR_WIDTH_EM * size))
        lines = textwrap.wrap(hook, width=width) or [""]
        limit = 1 if size == HOOK_FONT_SIZES[0] else HOOK_MAX_LINES
        if len(lines) <= limit:
            return "\n".join(lines), size
    return "\n".join(lines[:HOOK_MAX_LINES]), size


def text_paths(ass_path: Path):
    return (ass_path.with_name(f"{ass_path.stem}.hook.txt"),
            ass_path.with_name(f"{ass_path.stem}.credit.txt"))


def _layout_chain(plan: LayoutPlan) -> str:
    if plan.kind == "stream":
        c, g = plan.cam, plan.game
        return (
            f"[0:v]split=2[a][b];"
            f"[a]crop={c.w}:{c.h}:{c.x}:{c.y},scale={OUT_W}:{CAM_OUT_H}[cam];"
            f"[b]crop={g.w}:{g.h}:{g.x}:{g.y},scale={OUT_W}:{OUT_H - CAM_OUT_H}[game];"
            f"[cam][game]vstack=inputs=2[v0]"
        )
    if plan.kind == "face":
        f = plan.face
        return f"[0:v]crop={f.w}:{f.h}:{f.x}:{f.y},scale={OUT_W}:{OUT_H}[v0]"
    return (
        f"[0:v]split=2[a][b];"
        f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},boxblur=30:3[bg];"
        f"[b]scale={OUT_W}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]"
    )


def filter_graph(plan: LayoutPlan, ass_path: Path, hook: str, credit: str, dark: bool = False) -> str:
    """Pure: builds the video graph. Hook/credit text live in files next to the ASS."""
    hook_file, credit_file = text_paths(ass_path)
    _, size = wrap_hook(hook)
    bar_y = CAM_OUT_H - HOOK_BAR_H // 2 if plan.kind == "stream" else HOOK_BAR_TOP_Y
    font = escape_filter_path(font_path())
    tail = []
    if dark:
        tail.append(f"eq=brightness={BRIGHTNESS_LIFT}")
    tail += [
        f"drawbox=x=0:y={bar_y}:w=iw:h={HOOK_BAR_H}:color=black@{HOOK_BAR_ALPHA}:t=fill",
        f"drawtext=expansion=none:fontfile={font}:textfile={escape_filter_path(hook_file)}:fontsize={size}:"
        f"fontcolor=white:text_align=center:x=(w-text_w)/2:y={bar_y}+({HOOK_BAR_H}-text_h)/2",
        f"drawtext=expansion=none:fontfile={font}:textfile={escape_filter_path(credit_file)}:fontsize={CREDIT_FONT_SIZE}:"
        f"fontcolor=white@0.6:x={CREDIT_MARGIN}:y=h-text_h-{CREDIT_MARGIN}",
        f"ass={escape_filter_path(ass_path)}",
        f"fps={config.Settings.fps}",
        "format=yuv420p",
    ]
    return f"{_layout_chain(plan)};[v0]{','.join(tail)}[v]"


def audio_filter() -> str:
    return config.Settings.loudnorm


def command(src: Path, out: Path, graph: str, fast: bool) -> List[str]:
    s = config.Settings
    video = (["-c:v", s.fast_codec, "-b:v", FAST_VIDEO_BITRATE] if fast
             else ["-c:v", "libx264", "-crf", str(s.x264_crf), "-preset", "medium"])
    return [
        config.ffmpeg_bin(), "-y", "-v", "error", "-i", str(src),
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0?",
        "-af", audio_filter(), *video, "-pix_fmt", "yuv420p", "-r", str(s.fps),
        "-c:a", "aac", "-b:a", s.audio_bitrate, "-ar", "48000",
        "-movflags", "+faststart", str(out),
    ]


def _duration(src: Path) -> float:
    """Clip duration in seconds via ffprobe; 0.0 when unknown."""
    probe = Path(config.ffmpeg_bin()).with_name("ffprobe")
    cmd = [str(probe) if probe.exists() else "ffprobe", "-v", "error",
           "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(src)]
    try:
        return float(subprocess.run(cmd, capture_output=True, text=True).stdout.strip())
    except (ValueError, OSError):
        return 0.0


def parse_yavg(output: str) -> List[float]:
    return [float(v) for v in re.findall(r"YAVG=([0-9.]+)", output)]


def mean_luma(src: Path) -> float:
    """Mean luma (0-255) over ~LUMA_SAMPLE_FRAMES frames spread across the clip.

    Integration-only. On ffmpeg failure or no samples it prints one warning to stderr
    and returns NOT_DARK_LUMA (128.0), i.e. the clip is treated as not dark.
    """
    duration = _duration(src)
    rate = LUMA_SAMPLE_FRAMES / duration if duration > 0 else 1.0
    cmd = [config.ffmpeg_bin(), "-v", "error", "-i", str(src), "-vf",
           f"fps={rate:.6f},scale=320:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
           "-frames:v", str(LUMA_SAMPLE_FRAMES), "-an", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    values = parse_yavg(proc.stdout)
    if proc.returncode != 0 or not values:
        tail = proc.stderr.strip()[-200:]
        print(f"warning: luma measurement failed for {src}, assuming not dark: {tail}", file=sys.stderr)
        return NOT_DARK_LUMA
    return sum(values) / len(values)


def render(src: Path, out: Path, plan: LayoutPlan, ass_path: Path, hook: str, credit: str, fast: bool) -> Path:
    hook_file, credit_file = text_paths(ass_path)
    hook_file.write_text(wrap_hook(hook)[0], encoding="utf-8")
    credit_file.write_text(credit, encoding="utf-8")
    dark = mean_luma(src) < DARK_LUMA
    graph = filter_graph(plan, ass_path, hook, credit, dark=dark)
    proc = subprocess.run(command(src, out, graph, fast), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {proc.stderr[-STDERR_TAIL_CHARS:]}")
    if not out.exists():
        raise RuntimeError(f"ffmpeg finished but {out} was not created")
    return out
