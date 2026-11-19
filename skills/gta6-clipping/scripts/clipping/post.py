"""POST.md (ready-to-post text per clip), clips.json and report.json, written in the Mac work folder."""
import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Mapping, Sequence, Tuple

from .models import Moment, Stream

ClipItem = Tuple[Moment, Path]


def timestamp_link(stream: Stream, seconds: float) -> str:
    """Link to the stream at `seconds` (YouTube `t=Ns`, Twitch `t=XhYYmZZs`)."""
    total = int(seconds)
    if stream.platform == "twitch":
        stamp = f"{total // 3600}h{total // 60 % 60:02d}m{total % 60:02d}s"
    else:
        stamp = f"{total}s"
    sep = "&" if "?" in stream.url else "?"
    return f"{stream.url}{sep}t={stamp}"


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
          seconds: Mapping[str, float]) -> List[Path]:
    """Write POST.md, clips.json and report.json into `work_out`; return their paths."""
    work_out.mkdir(parents=True, exist_ok=True)
    report = {"stream": asdict(stream), "clips": len(items),
              "seconds": {k: round(v, 1) for k, v in seconds.items()}}
    contents = {
        "POST.md": render_md(stream, items),
        "clips.json": _clips_json(items),
        "report.json": json.dumps(report, ensure_ascii=False, indent=2),
    }
    paths = []
    for name, text in contents.items():
        path = work_out / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths
