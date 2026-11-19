"""Resume state per stream, kept on the stick: how far a (live) stream was processed
and which moments were already clipped."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from . import storage
from .config import Paths
from .models import Moment

DEFAULT_OVERLAP_S = 90.0
DEFAULT_CLIP_TOLERANCE_S = 20.0


@dataclass(frozen=True)
class RunState:
    processed_until: float = 0.0
    clipped: Tuple[Tuple[float, float], ...] = ()


def state_file(p: Paths, stream_id: str) -> Path:
    return p.state / f"{storage.safe_name(stream_id)}.json"


def load(path: Path) -> RunState:
    """State saved at `path`; an empty state when the file does not exist."""
    path = Path(path)
    if not path.exists():
        return RunState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunState(
        processed_until=float(data.get("processed_until", 0.0)),
        clipped=tuple((float(a), float(b)) for a, b in data.get("clipped", [])),
    )


def save(path: Path, s: RunState, root: Path, *, home_dev: Optional[int] = None) -> None:
    """Write the state through safe_path; never creates the archive root itself."""
    storage.require_archive_root(Path(root), home_dev)
    target = storage.safe_path(root, path)
    part = storage.safe_path(root, target.with_name(target.name + ".part"))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"processed_until": s.processed_until, "clipped": [list(c) for c in s.clipped]}
    try:
        part.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def next_section(s: RunState, now_duration: float,
                 overlap: float = DEFAULT_OVERLAP_S) -> Optional[Tuple[float, float]]:
    """The not-yet-processed part of a stream, starting `overlap` seconds early; None if nothing new."""
    if now_duration <= s.processed_until:
        return None
    return max(0.0, s.processed_until - overlap), now_duration


def already_clipped(s: RunState, m: Moment, tol: float = DEFAULT_CLIP_TOLERANCE_S) -> bool:
    """True when the moment overlaps (within `tol` seconds) a clip made earlier."""
    return any(m.start < end + tol and m.end > start - tol for start, end in s.clipped)


def advance(s: RunState, until: float, moments: Iterable[Moment]) -> RunState:
    """New state: processed at least up to `until`, with the moments' ranges added."""
    return RunState(
        processed_until=max(s.processed_until, until),
        clipped=s.clipped + tuple((m.start, m.end) for m in moments),
    )
