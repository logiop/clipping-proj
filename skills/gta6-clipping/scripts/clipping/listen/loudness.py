"""Loudness curve from ffmpeg astats, and spike detection."""
import re
import statistics
import subprocess
from pathlib import Path
from typing import List, Sequence, Tuple

MEASURE_TIMEOUT_S = 1800
_PTS = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(\S+)")
FILTER = "astats=metadata=1:reset=1,ametadata=print:file=-"


def parse_astats(text: str) -> List[Tuple[float, float]]:
    """(time, RMS dB) samples from ametadata output; silent (-inf) and nan frames are skipped."""
    samples = []
    current = None
    for line in text.splitlines():
        pts = _PTS.search(line)
        if pts:
            current = float(pts.group(1))
            continue
        rms = _RMS.search(line)
        if rms and current is not None:
            try:
                value = float(rms.group(1))
            except ValueError:
                continue
            if value == value and abs(value) != float("inf"):
                samples.append((current, value))
    return samples


def per_second(samples: Sequence[Tuple[float, float]]) -> List[float]:
    """Max dB per whole second; seconds without samples take the minimum value seen."""
    if not samples:
        return []
    peaks = {}
    for t, db in samples:
        sec = int(t)
        peaks[sec] = max(db, peaks.get(sec, db))
    floor = min(db for _, db in samples)
    return [peaks.get(s, floor) for s in range(max(peaks) + 1)]


def spikes(per_sec: Sequence[float], z: float = 2.0) -> List[Tuple[int, float]]:
    """Seconds at least z standard deviations above the median, as (second, dB above median)."""
    if len(per_sec) < 2:
        return []
    median = statistics.median(per_sec)
    deviation = statistics.pstdev(per_sec)
    if deviation == 0:
        return []
    return [(s, db - median) for s, db in enumerate(per_sec) if db - median >= z * deviation]


def measure(audio: Path) -> List[float]:
    """Per-second loudness (dB) of an audio file via ffmpeg. Raises RuntimeError on failure."""
    from .. import config
    cmd = [config.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(audio), "-af", FILTER, "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=MEASURE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"loudness measure timed out for {audio}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {audio}: {proc.stderr.strip()[-300:]}")
    return per_second(parse_astats(proc.stdout))
