"""Loudness curve from ffmpeg astats, and spike detection."""
import re
import statistics
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence, Tuple

MEASURE_TIMEOUT_S = 4 * 3600  # generous cap: a 12 h stream decodes in minutes at 16 kHz
_PTS = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(\S+)")
# 16 kHz mono-equivalent, 0.1 s frames, one overall RMS value printed per frame (~20 KB/min);
# printing every astats key per channel per frame was ~9 MB/min (6.7 GB for 12 h).
FILTER = ("aresample=16000,asetnsamples=n=1600,"
          "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level,"
          "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-")
SILENCE_DB = -60.0
MAD_TO_SIGMA = 1.4826
DEFAULT_SPIKE_Z = 1.0  # calibrated: 19 spikes on 10 min of Kai Cenat (VZqAPdUvqnQ 3600-4200)


def iter_astats(lines: Iterable[str]) -> Iterator[Tuple[float, float]]:
    """(time, RMS dB) samples from ametadata output lines; silent (-inf) and nan frames are skipped."""
    current = None
    for line in lines:
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
                yield current, value


def parse_astats(text: str) -> List[Tuple[float, float]]:
    """All samples of a captured ametadata output (see iter_astats)."""
    return list(iter_astats(text.splitlines()))


def per_second(samples: Iterable[Tuple[float, float]]) -> List[float]:
    """Max dB per whole second; seconds without samples take the minimum value seen.

    Consumes `samples` once, so a streaming iterator is reduced as it is read.
    """
    peaks = {}
    floor = None
    for t, db in samples:
        sec = int(t)
        peaks[sec] = max(db, peaks.get(sec, db))
        floor = db if floor is None else min(floor, db)
    if not peaks:
        return []
    return [peaks.get(s, floor) for s in range(max(peaks) + 1)]


def spikes(per_sec: Sequence[float], z: float = DEFAULT_SPIKE_Z) -> List[Tuple[int, float]]:
    """Loud seconds as (second, dB above median), by robust statistics.

    Seconds at or below SILENCE_DB (silence and per_second's gap fill) are ignored, so long
    quiet stretches cannot hide a yell. Threshold: median + z * 1.4826 * MAD of the remaining
    seconds; the population stdev is used when the MAD is 0 (a mostly flat signal).
    """
    voiced = [db for db in per_sec if db > SILENCE_DB]
    if len(voiced) < 2:
        return []
    median = statistics.median(voiced)
    scale = MAD_TO_SIGMA * statistics.median(abs(db - median) for db in voiced)
    if scale == 0:
        scale = statistics.pstdev(voiced)
    if scale == 0:
        return []
    return [(s, db - median) for s, db in enumerate(per_sec)
            if db > SILENCE_DB and db - median >= z * scale]


def measure(audio: Path, popen=subprocess.Popen) -> List[float]:
    """Per-second loudness (dB) of an audio file via ffmpeg, read as a stream (never held whole).

    Raises RuntimeError on failure or after MEASURE_TIMEOUT_S.
    """
    from .. import config
    cmd = [config.ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(audio), "-af", FILTER, "-f", "null", "-"]
    with tempfile.TemporaryFile(mode="w+") as err:
        proc = popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)
        timer = threading.Timer(MEASURE_TIMEOUT_S, proc.kill)
        timer.start()
        try:
            values = per_second(iter_astats(proc.stdout))
            code = proc.wait()
        finally:
            timer.cancel()
        if code != 0:
            err.seek(0)
            raise RuntimeError(f"ffmpeg loudness failed for {audio} (exit {code}): {err.read().strip()[-300:]}")
    return values
