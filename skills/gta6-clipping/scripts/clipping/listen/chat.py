"""Live-chat activity from yt-dlp's live_chat.json."""
import json
import statistics
from typing import Dict, Iterable, List, Tuple


def parse_live_chat(lines: Iterable[str]) -> List[float]:
    """Message offsets (seconds) from live_chat.json lines; malformed lines are skipped."""
    offsets = []
    for line in lines:
        try:
            data = json.loads(line)
            ms = data["replayChatItemAction"]["videoOffsetTimeMsec"]
            offsets.append(int(ms) / 1000.0)
        except (ValueError, KeyError, TypeError):
            continue
    return offsets


def rate(offsets: Iterable[float], bucket: int = 5) -> Dict[int, int]:
    """Message count per bucket, keyed by bucket start second (empty buckets omitted)."""
    counts: Dict[int, int] = {}
    for off in offsets:
        key = int(off // bucket) * bucket
        counts[key] = counts.get(key, 0) + 1
    return counts


def bursts(rate_by_bucket: Dict[int, int], factor: float = 3.0) -> List[Tuple[int, float]]:
    """Buckets with at least factor x the median count, as (bucket start, count / median)."""
    if not rate_by_bucket:
        return []
    median = max(statistics.median(rate_by_bucket.values()), 1)
    return [(start, count / median) for start, count in sorted(rate_by_bucket.items())
            if count >= factor * median]
