"""Shared data types and (de)serialization for work-folder stage files."""
import json
from dataclasses import asdict, dataclass, fields, is_dataclass
from typing import Optional, Type, TypeVar

from . import config
from .schemas import CATEGORIES, EVENTS, FALLBACK_EVENT

T = TypeVar("T")
MIN_SCORE, MAX_SCORE = 1, 100


@dataclass(frozen=True)
class Stream:
    id: str
    url: str
    platform: str
    streamer: str
    title: str
    duration: Optional[float]
    is_live: bool


@dataclass(frozen=True)
class Moment:
    start: float
    end: float
    score: int
    category: str
    event: str
    hook: str
    caption: str
    hashtags: tuple
    reason: str
    flags: tuple = ()


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_str_list(v) -> bool:
    return isinstance(v, (list, tuple)) and all(isinstance(x, str) for x in v)


def _fit_length(start: float, end: float, chunk_start: float, chunk_end: float):
    """Clamp to max length, or extend symmetrically (shifting at chunk edges) to min."""
    settings = config.Settings()
    if end - start > settings.max_clip_s:
        return start, start + settings.max_clip_s
    need = settings.min_clip_s - (end - start)
    if need <= 0:
        return start, end
    if chunk_end - chunk_start < settings.min_clip_s:
        return None
    new_start, new_end = start - need / 2, end + need / 2
    if new_start < chunk_start:
        new_start, new_end = chunk_start, chunk_start + settings.min_clip_s
    elif new_end > chunk_end:
        new_start, new_end = chunk_end - settings.min_clip_s, chunk_end
    return new_start, new_end


def moment_from_dict(d: dict, chunk_start: float, chunk_end: float) -> Optional[Moment]:
    """Build a Moment from a Claude reply item; None if invalid or outside the chunk."""
    if not isinstance(d, dict):
        return None
    try:
        start, end, score = d["start"], d["end"], d["score"]
        strings = [d[k] for k in ("category", "event", "hook", "caption", "reason")]
        hashtags, flags = d["hashtags"], d.get("flags", [])
    except KeyError:
        return None
    if not (_is_number(start) and _is_number(end)):
        return None
    if isinstance(score, bool) or not isinstance(score, int) or not MIN_SCORE <= score <= MAX_SCORE:
        return None
    if not all(isinstance(s, str) for s in strings) or not (_is_str_list(hashtags) and _is_str_list(flags)):
        return None
    category, event, hook, caption, reason = strings
    if category not in CATEGORIES or not chunk_start <= start < chunk_end or end <= start:
        return None
    fitted = _fit_length(start, min(end, chunk_end), chunk_start, chunk_end)
    if fitted is None:
        return None
    return Moment(
        start=fitted[0], end=fitted[1], score=score, category=category,
        event=event if event in EVENTS else FALLBACK_EVENT,
        hook=hook, caption=caption, hashtags=tuple(hashtags), reason=reason, flags=tuple(flags),
    )


def to_json(obj) -> str:
    """Serialize a dataclass (or list of them) to JSON text."""
    def conv(o):
        return asdict(o) if is_dataclass(o) else o
    data = [conv(o) for o in obj] if isinstance(obj, (list, tuple)) else conv(obj)
    return json.dumps(data, ensure_ascii=False, indent=2)


def from_json(cls: Type[T], text: str) -> T:
    """Inverse of to_json for a single dataclass; JSON arrays become tuples again."""
    data = json.loads(text)
    kwargs = {f.name: tuple(data[f.name]) if isinstance(data[f.name], list) else data[f.name]
              for f in fields(cls) if f.name in data}
    return cls(**kwargs)
