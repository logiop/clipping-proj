import json
from pathlib import Path

from clipping.models import Moment, Stream
from clipping.post import render_md, timestamp_link, write

YT = Stream(id="youtube:abc", url="https://www.youtube.com/watch?v=abc", platform="youtube",
            streamer="@Kai", title="GTA 6 day 1", duration=7200.0, is_live=False)
TW = Stream(id="twitch:v1", url="https://www.twitch.tv/videos/1", platform="twitch",
            streamer="@kai", title="t", duration=7200.0, is_live=False)


def _m(start=3725.0, flags=()):
    return Moment(start=start, end=start + 30, score=80, category="funny", event="first_drive",
                  hook="He crashed instantly", caption="First drive in GTA 6", hashtags=("#gta6", "#kai"),
                  reason="r", flags=flags)


def test_post_md_shows_flags_and_credit():
    md = render_md(YT, [(_m(flags=("non_english", "low_confidence")), Path("01.mp4"))])
    assert "01.mp4" in md
    assert "He crashed instantly" in md and "First drive in GTA 6" in md
    assert "#gta6 #kai" in md
    assert "credit: @Kai" in md
    assert "⚠ needs review: non_english, low_confidence" in md
    assert "https://www.youtube.com/watch?v=abc&t=3725s" in md


def test_post_md_without_flags_has_no_warning():
    assert "⚠" not in render_md(YT, [(_m(), Path("01.mp4"))])


def test_timestamp_link_per_platform():
    assert timestamp_link(YT, 61.7) == "https://www.youtube.com/watch?v=abc&t=61s"
    assert timestamp_link(TW, 3725) == "https://www.twitch.tv/videos/1?t=1h02m05s"


def test_write_puts_files_in_work_folder(tmp_path):
    out = tmp_path / "out"
    files = write(out, YT, [(_m(), Path("01.mp4"))], {"listen": 1.5, "pick": 2.0})
    assert [f.name for f in files] == ["POST.md", "clips.json", "report.json"]
    assert all(f.parent == out for f in files)
    clips = json.loads((out / "clips.json").read_text())
    assert clips[0]["file"] == "01.mp4" and clips[0]["hook"] == "He crashed instantly"
    assert json.loads((out / "report.json").read_text())["seconds"] == {"listen": 1.5, "pick": 2.0}
