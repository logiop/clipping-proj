"""Pick clip moments: chunk the transcript, annotate, ask Claude, select the top N."""
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import claude
from .listen.transcript import Segment
from .models import Moment, Stream, moment_from_dict
from .schemas import EVENTS, MOMENTS_SCHEMA

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "pick.md"
CHAT_BUCKET_S = 5
_DATA_TAG = re.compile(r"<(/?stream_data)", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
MIN_GAP_S = 60
MAX_LOUD_MARKS_PER_CHUNK = 12  # spikes are detected with a low z; only the loudest are worth a mark
CRASH_MESSAGE_CHARS = 200

Chunk = Tuple[float, float, List[Segment]]


@dataclass(frozen=True)
class PickResult:
    moments: List[Moment]
    failed: int  # chunks whose Claude call failed or crashed
    total: int   # chunks asked


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
    """Absolute stream seconds, the unit Claude must answer in: `[42930s]`."""
    return f"{int(seconds)}s"


def _loudest(chunk_segments: Sequence[Segment], spikes, limit: int = MAX_LOUD_MARKS_PER_CHUNK):
    """The `limit` spikes inside the chunk with the most dB above median (earlier first on ties)."""
    if not chunk_segments:
        return []
    start = min(s.start for s in chunk_segments)
    end = max(s.end for s in chunk_segments)
    inside = [(sec, db) for sec, db in spikes if start <= sec <= end]
    return sorted(inside, key=lambda sp: (-sp[1], sp[0]))[:limit]


def annotate(chunk_segments: Sequence[Segment], spikes, bursts) -> str:
    """One line per segment: `[Ns] text [LOUD +NdB] [CHAT xN]` (N = absolute stream seconds).

    Only the MAX_LOUD_MARKS_PER_CHUNK loudest spikes of the chunk are marked.
    """
    spikes = _loudest(chunk_segments, spikes)
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


def _neutralize(text: str) -> str:
    """Defang stream_data tags so stream text cannot close the data block."""
    return _DATA_TAG.sub(lambda m: "\u2039" + m.group(1), text)


def build_prompt(stream: Stream, chunk_text: str, start: float, end: float) -> str:
    """Fill prompts/pick.md in one pass, so braces in stream text are never re-substituted."""
    values = {
        "streamer": _neutralize(stream.streamer), "title": _neutralize(stream.title),
        "platform": _neutralize(stream.platform), "start": str(int(start)), "end": str(int(end)),
        "events": ", ".join(EVENTS), "chunk_text": _neutralize(chunk_text),
    }
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def select(moments: Sequence[Moment], n: int, min_gap: float = MIN_GAP_S) -> List[Moment]:
    """Highest score first; drop moments closer than `min_gap` to an already chosen one."""
    chosen: List[Moment] = []
    for m in sorted(moments, key=lambda m: m.score, reverse=True):
        if len(chosen) >= n:
            break
        if all(m.start >= c.end + min_gap or m.end + min_gap <= c.start for c in chosen):
            chosen.append(m)
    return chosen


def _pick_chunk(stream, chunk: Chunk, spikes, bursts, model, runner) -> Optional[List[Moment]]:
    """Moments for one chunk; None (logged) when the call failed or crashed."""
    try:
        return _pick_chunk_unsafe(stream, chunk, spikes, bursts, model, runner)
    except Exception as exc:  # one bad chunk must not abort the run
        label = f"{_timestamp(chunk[0])}-{_timestamp(chunk[1])}"
        detail = str(exc)[:CRASH_MESSAGE_CHARS]
        print(f"pick: chunk {label} crashed ({type(exc).__name__}: {detail}), skipped", file=sys.stderr)
        return None


def _pick_chunk_unsafe(stream, chunk: Chunk, spikes, bursts, model, runner) -> Optional[List[Moment]]:
    start, end, segs = chunk
    prompt = build_prompt(stream, annotate(segs, spikes, bursts), start, end)
    data = claude.ask(prompt, MOMENTS_SCHEMA, model, runner=runner)
    label = f"{_timestamp(start)}-{_timestamp(end)}"
    if data is None:
        print(f"pick: chunk {label} failed, skipped", file=sys.stderr)
        return None
    moments = [moment_from_dict(d, start, end) for d in data.get("moments", [])]
    return [m for m in moments if m is not None]


def pick(stream: Stream, segments, spikes, bursts, n: int, model: str,
         parallel: int = 4, runner=subprocess.run) -> PickResult:
    """Ask Claude per chunk (in parallel); the top-N non-overlapping moments and the failure count."""
    work = chunks(segments)
    if not work:
        return PickResult([], 0, 0)
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        results = list(pool.map(lambda c: _pick_chunk(stream, c, spikes, bursts, model, runner), work))
    found = [m for batch in results if batch is not None for m in batch]
    failed = sum(1 for batch in results if batch is None)
    return PickResult(select(found, n), failed, len(work))
