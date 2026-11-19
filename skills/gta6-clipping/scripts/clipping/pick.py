"""Pick clip moments: chunk the transcript, annotate, ask Claude, select the top N."""
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Sequence, Tuple

from . import claude
from .listen.transcript import Segment
from .models import Moment, Stream, moment_from_dict
from .schemas import EVENTS, MOMENTS_SCHEMA

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "pick.md"
CHAT_BUCKET_S = 5
MIN_GAP_S = 60

Chunk = Tuple[float, float, List[Segment]]


def chunks(segments: Sequence[Segment], minutes: int = 12) -> List[Chunk]:
    """Group segments into fixed windows of `minutes`; empty windows are skipped."""
    size = minutes * 60
    windows = {}
    for seg in segments:
        windows.setdefault(int(seg.start // size), []).append(seg)
    out = []
    last = max(windows, default=0)
    for idx in sorted(windows):
        group = windows[idx]
        end = (idx + 1) * size if idx < last else max(s.end for s in group)
        out.append((float(idx * size), float(end), group))
    return out


def _timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def annotate(chunk_segments: Sequence[Segment], spikes, bursts) -> str:
    """One line per segment: `[mm:ss] text [LOUD +NdB] [CHAT xN]`."""
    lines = []
    for seg in chunk_segments:
        line = f"[{_timestamp(seg.start)}] {seg.text}"
        loud = [db for sec, db in spikes if seg.start <= sec <= seg.end]
        if loud:
            line += f" [LOUD +{round(max(loud))}dB]"
        hot = [f for b, f in bursts if b < seg.end and b + CHAT_BUCKET_S > seg.start]
        if hot:
            line += f" [CHAT x{round(max(hot))}]"
        lines.append(line)
    return "\n".join(lines)


def build_prompt(stream: Stream, chunk_text: str, start: float, end: float) -> str:
    """Fill prompts/pick.md; plain replace so braces in transcript text are safe."""
    values = {
        "{streamer}": stream.streamer, "{title}": stream.title, "{platform}": stream.platform,
        "{start}": str(int(start)), "{end}": str(int(end)), "{events}": ", ".join(EVENTS),
    }
    template = PROMPT_PATH.read_text(encoding="utf-8")
    for key, value in values.items():
        template = template.replace(key, value)
    return template.replace("{chunk_text}", chunk_text)


def select(moments: Sequence[Moment], n: int, min_gap: float = MIN_GAP_S) -> List[Moment]:
    """Highest score first; drop moments closer than `min_gap` to an already chosen one."""
    chosen: List[Moment] = []
    for m in sorted(moments, key=lambda m: m.score, reverse=True):
        if len(chosen) >= n:
            break
        if all(m.start >= c.end + min_gap or m.end + min_gap <= c.start for c in chosen):
            chosen.append(m)
    return chosen


def _pick_chunk(stream, chunk: Chunk, spikes, bursts, model, runner) -> List[Moment]:
    start, end, segs = chunk
    prompt = build_prompt(stream, annotate(segs, spikes, bursts), start, end)
    data = claude.ask(prompt, MOMENTS_SCHEMA, model, runner=runner)
    label = f"{_timestamp(start)}-{_timestamp(end)}"
    if data is None:
        print(f"pick: chunk {label} failed, skipped", file=sys.stderr)
        return []
    moments = [moment_from_dict(d, start, end) for d in data.get("moments", [])]
    return [m for m in moments if m is not None]


def pick(stream: Stream, segments, spikes, bursts, n: int, model: str,
         parallel: int = 4, runner=subprocess.run) -> List[Moment]:
    """Ask Claude per chunk (in parallel) and return the top-N non-overlapping moments."""
    work = chunks(segments)
    if not work:
        return []
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        results = pool.map(lambda c: _pick_chunk(stream, c, spikes, bursts, model, runner), work)
        found = [m for batch in results for m in batch]
    return select(found, n)
