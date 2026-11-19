"""Visual check: is a candidate moment real gameplay (not menus, ads, BRB screens)?"""
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from . import claude
from .models import Moment
from .schemas import LOOK_SCHEMA

DEFAULT_FRAME_COUNT = 4
STATIC_DIFF_THRESHOLD = 2.0   # mean abs pixel diff (0-255) below which two frames count as identical
STATIC_DROP_SCORE = 0.98      # fallback: drop a moment whose frames are this static
NOT_GAMEPLAY_FLAG = "not_gameplay"
PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "look.md"

MomentFrames = Tuple[Moment, List[Path]]


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
    parents = {str(p.parent) for _, frames in items for p in frames}
    return Path(os.path.commonpath(sorted(parents)))


def _fallback(items: Sequence[MomentFrames]) -> List[Moment]:
    kept = []
    for m, frames in items:
        if static_score(frame_diffs(frames)) > STATIC_DROP_SCORE:
            print(f"look: dropping {m.start:.0f}-{m.end:.0f} (static screen)", file=sys.stderr)
            continue
        kept.append(m)
    return kept


def check(moments_with_frames: Sequence[MomentFrames], model: str,
          ask: Callable = claude.ask) -> List[Moment]:
    """Drop moments Claude judges non-gameplay; missing verdicts keep the moment."""
    items = list(moments_with_frames)
    if not items:
        return []
    prompt = PROMPT_PATH.read_text(encoding="utf-8").replace("{listing}", _listing(items))
    reply: Optional[dict] = ask(prompt, LOOK_SCHEMA, model, tools="Read", add_dir=_frames_dir(items))
    if reply is None:
        print("look: Claude visual check failed, using static-screen fallback", file=sys.stderr)
        return _fallback(items)
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
