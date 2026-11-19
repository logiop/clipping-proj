"""Visual check: is a candidate moment real gameplay (not menus, ads, BRB screens)?"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from . import claude
from .models import Moment
from .schemas import LOOK_SCHEMA

DEFAULT_FRAME_COUNT = 4
STATIC_DIFF_THRESHOLD = 2.0   # mean abs pixel diff (0-255) below which two frames count as identical
STATIC_DROP_SCORE = 0.98      # fallback: drop a moment whose frames are this static
NOT_GAMEPLAY_FLAG = "not_gameplay"
BATCH_SIZE = 5                # moments per Claude call (a few frames each)
DEFAULT_PARALLEL = 4
PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "look.md"

MomentFrames = Tuple[Moment, List[Path]]


@dataclass(frozen=True)
class LookResult:
    kept: List[Moment]
    failed: int  # batches whose Claude call failed (static-screen fallback used)
    total: int   # batches asked


def frame_times(m: Moment, k: int = DEFAULT_FRAME_COUNT) -> List[float]:
    """k times spread evenly strictly inside the moment."""
    step = (m.end - m.start) / (k + 1)
    return [m.start + step * (i + 1) for i in range(k)]


def static_score(frame_diffs: Sequence[float]) -> float:
    """Fraction of consecutive frame diffs below the static threshold, in [0, 1]."""
    if not frame_diffs:
        return 0.0
    return sum(1 for d in frame_diffs if d < STATIC_DIFF_THRESHOLD) / len(frame_diffs)


def frame_diffs(frames: Sequence[Path]) -> List[float]:
    """Mean absolute pixel difference between consecutive frames; unreadable frames are skipped."""
    import cv2
    import numpy as np
    images = [cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for p in frames]
    images = [i for i in images if i is not None]
    return [float(np.mean(cv2.absdiff(a, b))) for a, b in zip(images, images[1:]) if a.shape == b.shape]


def _listing(items: Sequence[MomentFrames]) -> str:
    lines = []
    for index, (m, frames) in enumerate(items):
        lines.append(f"Moment {index} ({m.start:.0f}s-{m.end:.0f}s, event: {m.event}):")
        lines.extend(f"  - {p}" for p in frames)
    return "\n".join(lines)


def _frames_dir(items: Sequence[MomentFrames]) -> Path:
    parents = {str(p.resolve().parent) for _, frames in items for p in frames}
    try:
        return Path(os.path.commonpath(sorted(parents)))
    except ValueError as exc:
        raise ValueError(f"frames have no common directory: {exc}") from exc


def _fallback(items: Sequence[MomentFrames]) -> List[Moment]:
    kept = []
    for m, frames in items:
        try:
            diffs = frame_diffs(frames)
        except ImportError as exc:
            print(f"look: cv2 unavailable ({exc}), keeping all moments", file=sys.stderr)
            return [mm for mm, _ in items]
        if static_score(diffs) > STATIC_DROP_SCORE:
            print(f"look: dropping {m.start:.0f}-{m.end:.0f} (static screen)", file=sys.stderr)
            continue
        kept.append(m)
    return kept


def _check_forbid(frames_dir: Path, forbid: Tuple[Path, ...]) -> None:
    for path in forbid:
        resolved = path.resolve()
        if resolved == frames_dir or frames_dir in resolved.parents:
            raise ValueError(f"frames directory {frames_dir} would expose {resolved}; use a dedicated frames/ folder")


def _apply_verdicts(items: Sequence[MomentFrames], reply: dict) -> List[Moment]:
    rejected = {v["index"]: v["why"] for v in reply["verdicts"] if not v["gameplay"]}
    kept = []
    for index, (m, _) in enumerate(items):
        if index in rejected:
            flagged = replace(m, flags=m.flags + (NOT_GAMEPLAY_FLAG,))
            print(f"look: dropping {flagged.start:.0f}-{flagged.end:.0f} ({NOT_GAMEPLAY_FLAG}: {rejected[index]})",
                  file=sys.stderr)
            continue
        kept.append(m)
    return kept


def _check_batch(items: Sequence[MomentFrames], model: str, ask: Callable) -> Tuple[List[Moment], bool]:
    """(kept moments, whether the Claude call failed) for one batch."""
    prompt = PROMPT_PATH.read_text(encoding="utf-8").replace("{listing}", _listing(items))
    reply: Optional[dict] = ask(prompt, LOOK_SCHEMA, model, tools="Read", add_dir=_frames_dir(items))
    if reply is None:
        span = f"{items[0][0].start:.0f}s-{items[-1][0].end:.0f}s"
        print(f"look: WARNING Claude visual check failed for {len(items)} moments ({span}), "
              "using static-screen fallback", file=sys.stderr)
        return _fallback(items), True
    return _apply_verdicts(items, reply), False


def check(moments_with_frames: Sequence[MomentFrames], model: str, ask: Callable = claude.ask,
          forbid: Tuple[Path, ...] = (), parallel: int = DEFAULT_PARALLEL) -> LookResult:
    """Drop moments Claude judges non-gameplay; missing verdicts keep the moment.

    Moments go to Claude BATCH_SIZE at a time, `parallel` calls at once; a failed batch
    falls back to the static-screen check on its own. Claude gets read access to each
    batch's frames directory, so callers keep frames in a dedicated `frames/` subfolder and
    pass the work root (and anything else sensitive) in `forbid`; ValueError is raised if a
    frames directory equals or contains a forbidden path.
    """
    items = list(moments_with_frames)
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    for batch in batches:
        _check_forbid(_frames_dir(batch), forbid)
    if not batches:
        return LookResult([], 0, 0)
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        results = list(pool.map(lambda b: _check_batch(b, model, ask), batches))
    kept = [m for batch_kept, _ in results for m in batch_kept]
    return LookResult(kept, sum(1 for _, failed in results if failed), len(batches))
