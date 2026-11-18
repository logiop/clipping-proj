"""Rank candidate highlight windows from per-chunk RMS loudness + scene-change density.
Usage: python3 -I peaks.py rms.txt scenes.txt [top_n]"""
import re, sys, statistics

WINDOW_SEC = 25
MIN_GAP_SEC = 60


def parse_rms(path):
    t, out = 0.0, []
    for line in open(path):
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
        m = re.search(r"RMS_level=(-?[\d.]+|-inf)", line)
        if m and m.group(1) != "-inf":
            out.append((t, float(m.group(1))))
    return out


def per_second(samples):
    buckets = {}
    for t, v in samples:
        buckets.setdefault(int(t), []).append(v)
    return {s: max(v) for s, v in buckets.items()}


def scene_times(path):
    return [float(m.group(1)) for m in (re.search(r"pts_time:([\d.]+)", l) for l in open(path)) if m]


def zscores(values):
    mean = statistics.fmean(values.values())
    sd = statistics.pstdev(values.values()) or 1.0
    return {k: (v - mean) / sd for k, v in values.items()}


def rank(rms_path, scenes_path, top_n):
    z = zscores(per_second(parse_rms(rms_path)))
    scenes = scene_times(scenes_path)
    horizon = max(z)
    scored = []
    for start in range(0, horizon - WINDOW_SEC):
        loud = sum(z.get(s, 0) for s in range(start, start + WINDOW_SEC)) / WINDOW_SEC
        cuts = sum(1 for c in scenes if start <= c < start + WINDOW_SEC)
        scored.append((loud + 0.15 * cuts, start, cuts))
    picked = []
    for score, start, cuts in sorted(scored, reverse=True):
        if all(abs(start - p[1]) >= MIN_GAP_SEC for p in picked):
            picked.append((score, start, cuts))
        if len(picked) == top_n:
            break
    return picked


if __name__ == "__main__":
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    for score, start, cuts in sorted(rank(sys.argv[1], sys.argv[2], n), key=lambda p: p[1]):
        print(f"{start//60:02d}:{start%60:02d}  score={score:.2f}  cuts={cuts}")
