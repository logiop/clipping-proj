"""Per-stream stages, all inside the Mac work folder. Each stage with a JSON output
(listen.json, moments.json, selected.json, clips/NN.json) is skipped when that file
exists, unless Options.redo is set. Failure counts for the run report go to notes.json."""
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import captions, config, fetch, layout, look, pick, render, ytdlp
from .listen import audio, chat, loudness, transcript
from .listen.transcript import Segment
from .models import Moment, Stream

LAYOUT_SAMPLES = 8
CHAT_TIMEOUT_S = 600
WAV_TIMEOUT_S = 300
NOTES = "notes.json"
Section = Optional[Tuple[float, float]]
Heard = Tuple[list, list, list]  # (segments, spikes, bursts), all in stream time


@dataclass(frozen=True)
class Options:
    clips: int = 3
    model: str = "sonnet"
    cookies: Optional[str] = None
    layout: str = "auto"
    fast: bool = False
    redo: bool = False
    keep_work: bool = False
    pick_parallel: int = 4
    section: Section = None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cached(path: Path, redo: bool, compute: Callable, encode: Callable, decode: Callable):
    """decode(json at path) when present and not redo; else compute, save encode(value), return it."""
    if path.exists() and not redo:
        return decode(json.loads(path.read_text(encoding="utf-8")))
    value = compute()
    _write_json(path, encode(value))
    return value


def read_notes(work: Path) -> dict:
    """Failure counts recorded by the stages of this work folder ({} when none)."""
    path = work / NOTES
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def add_notes(work: Path, **values) -> None:
    _write_json(work / NOTES, {**read_notes(work), **values})


def moment_to_dict(m: Moment) -> dict:
    return asdict(m)


def moment_from_dict(d: dict) -> Moment:
    names = {f.name for f in fields(Moment)}
    return Moment(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items() if k in names})


def chat_bursts(stream: Stream, work: Path, section: Section, cookies: Optional[str],
                runner: Callable = subprocess.run) -> list:
    """Chat bursts (stream time) from YouTube chat replay; [] when there is no chat or it fails."""
    if stream.platform != "youtube" or stream.is_live:
        return []
    base = work / "chat"
    cmd = ytdlp.base_args(cookies) + ["--skip-download", "--write-subs", "--sub-langs", "live_chat",
                                      "--no-playlist", "-o", str(base), stream.url]
    try:
        proc = runner(cmd, capture_output=True, text=True, timeout=CHAT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print(f"chat: replay download timed out for {stream.url}, continuing without chat", file=sys.stderr)
        return []
    found = Path(str(base) + ".live_chat.json")
    if proc.returncode != 0 or not found.exists():
        return []
    with found.open(encoding="utf-8") as fh:
        offsets = chat.parse_live_chat(fh)
    if section is not None:
        offsets = [o for o in offsets if section[0] <= o < section[1]]
    return chat.bursts(chat.rate(offsets))


def audio_path(work: Path, section: Section) -> Path:
    """The stream audio file; named per section, so an audio file left by an earlier run is
    only reused for the same section."""
    if section is None:
        return work / "audio.m4a"
    return work / f"audio_{section[0]:.2f}-{section[1]:.2f}.m4a"


def _listen(stream: Stream, work: Path, section: Section, opts: Options) -> Heard:
    track = audio.download(stream, section, audio_path(work, section), opts.cookies)
    offset = section[0] if section is not None else 0.0
    spikes = [(sec + offset, db) for sec, db in loudness.spikes(loudness.measure(track))]
    segments = transcript.get(stream, track, opts.cookies, section=section)
    return segments, spikes, chat_bursts(stream, work, section, opts.cookies)


def cached_section_differs(work: Path, section: Section) -> bool:
    """True when listen.json exists but was made for another section (its later stages are stale)."""
    path = work / "listen.json"
    if not path.exists():
        return False
    saved = json.loads(path.read_text(encoding="utf-8")).get("section")
    return saved != (list(section) if section is not None else None)


def listen_stage(stream: Stream, work: Path, section: Section, opts: Options) -> Heard:
    def encode(heard):
        segments, spikes, bursts = heard
        return {"section": section, "segments": [asdict(s) for s in segments],
                "spikes": [list(s) for s in spikes], "bursts": [list(b) for b in bursts]}

    def decode(d):
        return ([Segment(**s) for s in d["segments"]], [tuple(s) for s in d["spikes"]],
                [tuple(b) for b in d["bursts"]])

    return _cached(work / "listen.json", opts.redo, lambda: _listen(stream, work, section, opts), encode, decode)


def _moments_cache(path: Path, opts: Options, compute: Callable) -> List[Moment]:
    return _cached(path, opts.redo, compute, lambda ms: [moment_to_dict(m) for m in ms],
                   lambda d: [moment_from_dict(x) for x in d])


def _pick(stream: Stream, work: Path, heard: Heard, opts: Options) -> List[Moment]:
    segments, spikes, bursts = heard
    result = pick.pick(stream, segments, spikes, bursts, n=2 * opts.clips, model=opts.model,
                       parallel=opts.pick_parallel)
    if result.total and result.failed == result.total:
        raise RuntimeError(f"all {result.total} Claude pick calls failed; nothing cached, run again later")
    add_notes(work, pick_failed_chunks=result.failed, pick_chunks=result.total)
    return result.moments


def pick_stage(stream: Stream, work: Path, heard: Heard, opts: Options) -> List[Moment]:
    """Candidate moments; RuntimeError (and no moments.json) when every Claude call failed."""
    return _moments_cache(work / "moments.json", opts, lambda: _pick(stream, work, heard, opts))


def _look(stream: Stream, work: Path, candidates: List[Moment], opts: Options, p: config.Paths) -> List[Moment]:
    items = []
    for i, m in enumerate(candidates):
        try:
            items.append((m, fetch.moment_frames(stream, m, work / "frames" / str(i), opts.cookies)))
        except RuntimeError as exc:
            print(f"look: no frames for {m.start:.0f}-{m.end:.0f}, dropped ({exc})", file=sys.stderr)
    if not items:
        return []
    result = look.check(items, opts.model, forbid=(p.work, work), parallel=opts.pick_parallel)
    add_notes(work, look_failed_batches=result.failed, look_batches=result.total)
    best = sorted(result.kept, key=lambda m: m.score, reverse=True)[:opts.clips]
    return sorted(best, key=lambda m: m.start)


def look_stage(stream: Stream, work: Path, candidates: List[Moment], opts: Options,
               p: config.Paths) -> List[Moment]:
    """Visual check of the candidates; the top `clips` by score, ordered by start time."""
    return _moments_cache(work / "selected.json", opts, lambda: _look(stream, work, candidates, opts, p))


def _sample_frames(clip: Path, k: int) -> Tuple[list, int, int]:
    import cv2
    cap = cv2.VideoCapture(str(clip))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frames = []
        for i in range(k):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / k))
            ok, frame = cap.read()
            if ok:
                frames.append(frame)
    finally:
        cap.release()
    return frames, width, height


def layout_for(clip: Path, forced: str, detect: Callable = layout.detect_faces) -> layout.LayoutPlan:
    """Sample frames evenly from the clip, find faces, plan the vertical layout."""
    frames, width, height = _sample_frames(clip, LAYOUT_SAMPLES)
    if not frames:
        raise RuntimeError(f"cannot read frames from {clip}")
    faces = [detect(f) for f in frames]
    cam = layout.facecam_box(faces, width, height)
    return layout.plan(width, height, cam, forced=forced, big_face=layout.big_face(faces, width, height))


def extract_wav(clip: Path, wav: Path, runner: Callable = subprocess.run) -> Path:
    """Mono 16 kHz wav of the clip's audio (for word captions)."""
    cmd = [config.ffmpeg_bin(), "-y", "-v", "error", "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(wav)]
    proc = runner(cmd, capture_output=True, text=True, timeout=WAV_TIMEOUT_S)
    if proc.returncode != 0 or not wav.exists():
        raise RuntimeError(f"audio extraction failed for {clip}: {proc.stderr.strip()[-300:]}")
    return wav


def _timed(timings: Dict[str, float], name: str, fn: Callable):
    started = time.monotonic()
    value = fn()
    return value, {**timings, name: time.monotonic() - started}


def _make_clip(stream: Stream, work: Path, nn: str, m: Moment, opts: Options):
    clips, out = work / "clips", work / "out" / f"{nn}.mp4"
    clip = clips / f"{nn}.mp4"
    raw, t = _timed({}, "fetch", lambda: fetch.download_clip(stream, m, clips, opts.cookies))
    os.replace(raw, clip)
    plan, t = _timed(t, "layout", lambda: layout_for(clip, opts.layout))
    print(f"layout {nn}: {plan.kind}", file=sys.stderr, flush=True)
    (ass_text, flags), t = _timed(t, "captions", lambda: captions.make(extract_wav(clip, clips / f"{nn}.wav"), 0.0))
    ass = clips / f"{nn}.ass"
    ass.write_text(ass_text, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    _, t = _timed(t, "render", lambda: render.render(clip, out, plan, ass, m.hook, stream.streamer, opts.fast))
    merged = replace(m, flags=m.flags + tuple(f for f in dict.fromkeys(flags) if f not in m.flags))
    return merged, out, t


def clip_stage(stream: Stream, work: Path, nn: str, m: Moment, opts: Options) -> Tuple[Moment, Path, dict]:
    """Fetch 1080p, plan layout, caption and render clip `nn`; returns (moment+flags, rendered, seconds)."""
    record, out = work / "clips" / f"{nn}.json", work / "out" / f"{nn}.mp4"
    if record.exists() and out.exists() and not opts.redo:
        return moment_from_dict(json.loads(record.read_text(encoding="utf-8"))), out, {}
    merged, out, timings = _make_clip(stream, work, nn, m, opts)
    _write_json(record, moment_to_dict(merged))
    return merged, out, timings
