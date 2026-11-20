"""Side-by-side table of a --pick-only result against earlier runs' clips_*.json files.

Usage: python compare_picks.py NEW_COMPARE_JSON OLD_CLIPS_JSON [OLD_CLIPS_JSON ...]
A new moment "matches" an old clip when they overlap by at least half of the shorter one.
"""
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

MIN_OVERLAP = 0.5


def overlap(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Shared seconds divided by the shorter span (0 when disjoint)."""
    shared = min(a[1], b[1]) - max(a[0], b[0])
    shorter = min(a[1] - a[0], b[1] - b[0])
    return max(0.0, shared) / shorter if shorter > 0 else 0.0


def match(new: List[dict], old: List[dict], min_overlap: float = MIN_OVERLAP) -> List[Tuple[dict, Optional[dict]]]:
    """Each new moment paired with the old clip it overlaps most (None below min_overlap)."""
    pairs = []
    for n in new:
        span = (n["start"], n["end"])
        best = max(old, key=lambda o: overlap(span, (o["start"], o["end"])), default=None)
        ok = best is not None and overlap(span, (best["start"], best["end"])) >= min_overlap
        pairs.append((n, best if ok else None))
    return pairs


def _load_old(paths: Sequence[str]) -> List[dict]:
    rows = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        rows += data if isinstance(data, list) else data.get("clips", [])
    return rows


def _row(n: dict, o: Optional[dict]) -> str:
    left = f"{n['start']:>6.0f}s  {n.get('score', ''):>3}  {n.get('event', ''):<18} {n.get('hook', '')[:50]:<50}"
    right = f"{o['file']}  {o.get('hook', '')[:40]}" if o else "-"
    return f"{left} | {right}"


def main(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        new = json.loads(Path(argv[0]).read_text(encoding="utf-8"))["moments"]
        old = _load_old(argv[1:])
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"compare_picks: cannot read input ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2
    pairs = match(new, old)
    for n, o in pairs:
        print(_row(n, o))
    print(f"matches: {sum(1 for _, o in pairs if o)}/{len(pairs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
