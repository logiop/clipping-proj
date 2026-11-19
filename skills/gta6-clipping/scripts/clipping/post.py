"""POST.md (ready-to-post text per clip), clips.json and report.json, written in the Mac work folder."""
import json
import urllib.parse
from dataclasses import asdict
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple

from .models import Moment, Stream

ClipItem = Tuple[Moment, Path]


def timestamp_link(stream: Stream, seconds: float) -> str:
    """Link to the stream at `seconds` (YouTube `t=Ns`, Twitch `t=XhYYmZZs`)."""
    total = int(seconds)
    if stream.platform == "twitch":
        stamp = f"{total // 3600}h{total // 60 % 60:02d}m{total % 60:02d}s"
    else:
        stamp = f"{total}s"
    parts = urllib.parse.urlsplit(stream.url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k != "t"]
    query.append(("t", stamp))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _clip_md(stream: Stream, m: Moment, file: Path) -> List[str]:
    lines = [
        f"## {file.name}",
        "",
        f"- hook: {m.hook}",
        f"- caption: {m.caption}",
        f"- hashtags: {' '.join(m.hashtags)}",
        f"- credit: {stream.streamer}",
        f"- link: {timestamp_link(stream, m.start)}",
        f"- event: {m.event} (score {m.score})",
    ]
    if m.flags:
        lines.append(f"- ⚠ needs review: {', '.join(m.flags)}")
    return lines + [""]


def render_md(stream: Stream, items: Sequence[ClipItem]) -> str:
    lines = [f"# {stream.streamer} — {stream.title}", "", f"Source: {stream.url}", ""]
    for m, file in items:
        lines.extend(_clip_md(stream, m, file))
    return "\n".join(lines)


def _clips_json(items: Sequence[ClipItem]) -> str:
    rows = [{"file": file.name, **asdict(m)} for m, file in items]
    return json.dumps(rows, ensure_ascii=False, indent=2)


def write(work_out: Path, stream: Stream, items: Sequence[ClipItem],
          seconds: Mapping[str, float], stamp: str, notes: Optional[Mapping] = None) -> List[Path]:
    """Write POST_<stamp>.md, clips_<stamp>.json and report_<stamp>.json into `work_out`.

    The stamp (run start time) keeps several runs of one stream in the same day folder apart.
    `notes` (failure counts such as failed_clips, pick_failed_chunks) are added to the report.
    """
    work_out.mkdir(parents=True, exist_ok=True)
    report = {"stream": asdict(stream), "clips": len(items),
              "seconds": {k: round(v, 1) for k, v in seconds.items()}, **(notes or {})}
    contents = {
        f"POST_{stamp}.md": render_md(stream, items),
        f"clips_{stamp}.json": _clips_json(items),
        f"report_{stamp}.json": json.dumps(report, ensure_ascii=False, indent=2),
    }
    paths = []
    for name, text in contents.items():
        path = work_out / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths
