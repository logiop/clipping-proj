import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from clipping import config, render
from clipping.layout import Box, LayoutPlan

FF = config.ffmpeg_bin()
HOOK = "It's HERE: 100% real \\ wow"

STREAM = LayoutPlan("stream", 1920, 1080, cam=Box(1400, 0, 480, 286), game=Box(656, 0, 608, 1080))
FACE = LayoutPlan("face", 1920, 1080, face=Box(656, 0, 608, 1080))
FIT = LayoutPlan("fit", 1920, 1080)


def graph(plan=STREAM, **kw):
    return render.filter_graph(plan, Path("/w/cap.ass"), HOOK, "@someone", **kw)


def test_graph_uses_textfile_not_inline_text():
    g = graph()
    assert "textfile=" in g
    assert "It's" not in g and "100%" not in g and "@someone" not in g


def test_graph_has_loudnorm_minus_14():
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in render.audio_filter()


def test_fast_uses_videotoolbox():
    cmd = render.command(Path("a.mp4"), Path("b.mp4"), "g", fast=True)
    assert "h264_videotoolbox" in cmd and "-b:v" in cmd and "libx264" not in cmd


def test_slow_uses_libx264_crf20():
    cmd = render.command(Path("a.mp4"), Path("b.mp4"), "g", fast=False)
    assert "libx264" in cmd and cmd[cmd.index("-crf") + 1] == "20"
    assert "192k" in cmd and "+faststart" in cmd and "yuv420p" in cmd
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in cmd[cmd.index("-af") + 1]


def test_dark_adds_brightness_lift():
    assert "eq=brightness=0.06" in graph(dark=True)
    assert "eq=brightness" not in graph()


def test_hook_bar_position_by_kind():
    assert "drawbox=x=0:y=575" in graph(STREAM)
    assert "drawbox=x=0:y=300" in graph(FACE)
    assert "fontcolor=white@0.6" in graph(FIT)


def test_graph_per_kind_structure():
    assert "vstack" in graph(STREAM)
    assert "crop=608:1080:656:0" in graph(FACE) and "vstack" not in graph(FACE)
    assert "boxblur" in graph(FIT) and "overlay" in graph(FIT)


def test_escape_filter_path():
    assert render.escape_filter_path("/a/b.ass") == "/a/b.ass"
    e = render.escape_filter_path("/a b/c:d'e.ass")
    assert ":" not in e.replace("\\:", "") and "'" not in e.replace("\\'", "")


def test_wrap_hook_at_most_two_lines():
    text, size = render.wrap_hook("word " * 40)
    assert len(text.split("\n")) <= 2 and size >= 30
    short, big = render.wrap_hook("SHORT")
    assert "\n" not in short and big > size


def has_ass():
    out = subprocess.run([FF, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return " ass " in out and "drawtext" in out


ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,2,10,10,520,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,HELLO WORLD
"""


def probe(path):
    p = subprocess.run([str(Path(FF).with_name("ffprobe")), "-v", "error", "-show_streams",
                        "-show_format", "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(p.stdout)


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    d = tmp_path_factory.mktemp("synth")
    src = d / "src.mp4"
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
    return src


@pytest.mark.skipif(not has_ass(), reason="ffmpeg lacks ass/drawtext")
@pytest.mark.parametrize("plan", [STREAM, FACE, FIT], ids=lambda p: p.kind)
def test_render_synthetic_clip(synthetic, tmp_path, plan):
    work = tmp_path / "work dir: it's"
    work.mkdir()
    ass = work / "captions.ass"
    ass.write_text(ASS)
    out = tmp_path / f"{plan.kind}.mp4"
    result = render.render(synthetic, out, plan, ass, HOOK + " and a much longer tail of words", "@streamer", fast=False)
    assert result == out and out.exists()
    info = probe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.5
    if plan.kind == "stream":
        png = Path(tempfile.gettempdir()) / "gta6_render_stream_frame.png"
        subprocess.run([FF, "-y", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", str(png)], check=True)
        assert png.exists()
        print("FRAME_PNG", png)


@pytest.mark.skipif(not has_ass(), reason="ffmpeg lacks ass/drawtext")
def test_render_raises_with_stderr_tail(tmp_path):
    ass = tmp_path / "c.ass"
    ass.write_text(ASS)
    with pytest.raises(RuntimeError):
        render.render(tmp_path / "missing.mp4", tmp_path / "o.mp4", FIT, ass, "h", "@s", fast=True)


@pytest.mark.skipif(not has_ass(), reason="ffmpeg lacks ass/drawtext")
def test_mean_luma(synthetic, tmp_path):
    dark = tmp_path / "dark.mp4"
    subprocess.run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:size=320x180:duration=2",
                    str(dark)], check=True)
    assert render.mean_luma(dark) < 60
    assert render.mean_luma(synthetic) > 60
