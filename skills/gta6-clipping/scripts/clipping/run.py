"""gta6clip: find -> listen -> pick -> visual check -> fetch -> layout -> captions -> render
-> archive to the stick. Resumable: stage files live in ~/gta6-clips/work/<stream>/.
CLI: python -m clipping.run [URL ...] (see --help)."""
import argparse
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from . import archiving, config, doctor, find, post, stages, state, storage, ytdlp
from .archiving import archive_stream, out_dir  # noqa: F401 (public API of run)
from .layout import FORCED_VALUES
from .models import Moment, Stream

DEFAULT_STREAMS = 3
DEFAULT_PARALLEL = 2
DEFAULT_PICK_PARALLEL = 4
PLATFORMS = ("youtube", "twitch")
CLIP_ERROR_CHARS = 200
WHOLE_STREAM_DONE = 1e9  # processed-until for a stream of unknown length: done once processed whole


def parse_time(text: str) -> float:
    """Seconds from `S`, `M:SS` or `H:MM:SS`."""
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"bad time: {text!r}")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def parse_section(text: str) -> Tuple[float, float]:
    start, sep, end = text.partition("-")
    if not sep:
        raise ValueError(f"section must be A-B, got {text!r}")
    a, b = parse_time(start), parse_time(end)
    if not 0 <= a < b:
        raise ValueError(f"section start must be before its end: {text!r}")
    return a, b


def _section_arg(text: str) -> Tuple[float, float]:
    try:
        return parse_section(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    settings = config.load()
    ap = argparse.ArgumentParser(prog="gta6clip", description="Vertical GTA 6 clips from streams, archived to the stick.")
    ap.add_argument("urls", nargs="*", metavar="URL", help="stream/VOD links (none: find streams)")
    ap.add_argument("--find", action="store_true", help="also find recent GTA 6 streams")
    ap.add_argument("--list", action="store_true", help="only list found streams")
    ap.add_argument("--streams", type=_positive_int, default=DEFAULT_STREAMS, help="streams to find")
    ap.add_argument("--clips", type=_positive_int, default=settings.clips_per_stream, help="clips per stream")
    ap.add_argument("--section", type=_section_arg, help="only A-B of the stream (s, m:ss or h:mm:ss)")
    ap.add_argument("--cookies", metavar="BROWSER", help="browser to read cookies from")
    ap.add_argument("--layout", choices=FORCED_VALUES, default="auto")
    ap.add_argument("--model", default=settings.model, help="Claude model for picking and checking")
    ap.add_argument("--fast", action="store_true", help="hardware encoder")
    ap.add_argument("--redo", action="store_true", help="ignore saved stage files")
    ap.add_argument("--keep-work", action="store_true", help="keep the Mac work folder after archiving")
    ap.add_argument("--parallel", type=_positive_int, default=DEFAULT_PARALLEL, help="streams at a time")
    ap.add_argument("--pick-parallel", type=_positive_int, default=DEFAULT_PICK_PARALLEL, help="Claude pick calls at a time")
    return ap


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def options(args: argparse.Namespace) -> stages.Options:
    return stages.Options(clips=args.clips, model=args.model, cookies=args.cookies, layout=args.layout,
                          fast=args.fast, redo=args.redo, keep_work=args.keep_work,
                          pick_parallel=args.pick_parallel, section=args.section)


def stream_from_url(url: str, cookies: Optional[str], info: Callable = ytdlp.info,
                    now: Callable = time.time) -> Stream:
    data = info(url, cookies)
    extractor = str(data.get("extractor_key") or data.get("extractor") or "").lower()
    platform = next((p for p in PLATFORMS if p in extractor), None)
    if platform is None:
        raise ValueError(f"unsupported platform for {url}: {extractor or 'unknown'}")
    handle = str(data.get("uploader_id") or "")
    if not handle.startswith("@"):
        handle = "@" + str(data.get("channel") or data.get("uploader") or handle).replace(" ", "")
    is_live = data.get("live_status") == "is_live"
    duration = data.get("duration")
    if is_live and not duration:
        started = data.get("release_timestamp") or data.get("timestamp")
        duration = now() - started if started else None
    return Stream(id=f"{platform}:{data['id']}", url=url, platform=platform, streamer=handle,
                  title=data.get("title") or "", duration=duration, is_live=is_live)


def choose_section(stream: Stream, s: state.RunState,
                   explicit: stages.Section) -> Optional[Tuple[stages.Section, float]]:
    """(audio section or None for all, processed-until) — or None when a live stream has nothing new.

    A VOD without --section is processed whole on every run (already-clipped moments are
    filtered later). A stream without a known duration is processed whole and marked done.
    """
    if explicit is not None:
        return explicit, explicit[1]
    if not stream.duration:
        return None, WHOLE_STREAM_DONE
    if stream.is_live:
        nxt = state.next_section(s, float(stream.duration))
        return (nxt, nxt[1]) if nxt else None
    return None, float(stream.duration)


def _log(label: str, stage: str, seconds: float) -> None:
    print(f"[{label}] {stage}: {seconds:.0f} s", flush=True)


def _timed(label: str, stage: str, fn: Callable):
    started = time.monotonic()
    value = fn()
    elapsed = time.monotonic() - started
    _log(label, stage, elapsed)
    return value, elapsed


def _select(stream, work, section, opts, p, s, label) -> Tuple[List[Moment], dict]:
    heard, t_listen = _timed(label, "listen", lambda: stages.listen_stage(stream, work, section, opts))
    found, t_pick = _timed(label, "pick", lambda: stages.pick_stage(stream, work, heard, opts))
    fresh = [m for m in found if not state.already_clipped(s, m)]
    chosen, t_look = _timed(label, "look", lambda: stages.look_stage(stream, work, fresh, opts, p))
    return chosen, {"listen": t_listen, "pick": t_pick, "look": t_look}


def _make_clips(stream, work, chosen, opts, label, meta) -> Tuple[List[Tuple[Moment, Path]], dict, int]:
    """(made clips, summed stage seconds, failed count); one failing clip is logged and left out."""
    items, totals, failed = [], {}, 0
    for i, m in enumerate(chosen):
        nn = archiving.clip_name(meta, i)
        try:
            moment, out, timings = stages.clip_stage(stream, work, nn, m, opts)
        except Exception as exc:  # one bad clip must not block the rest of the stream
            failed += 1
            print(f"[{label}] clip {nn} failed ({m.start:.0f}-{m.end:.0f} s): {type(exc).__name__}: "
                  f"{str(exc)[:CLIP_ERROR_CHARS]}", flush=True)
            continue
        items.append((moment, out))
        totals = {k: totals.get(k, 0.0) + timings.get(k, 0.0) for k in {*totals, *timings}}
    for stage in ("fetch", "layout", "captions", "render"):
        _log(label, stage, totals.get(stage, 0.0))
    return items, totals, failed


def _finish(stream, work, items, seconds, opts, p, meta, label, save_state, notes) -> List[Path]:
    posted = post.write(work / "out", stream, [(m, Path(out.name)) for m, out in items], seconds, meta.stamp,
                        notes=notes)
    files = [out for _, out in items] + posted
    archived, _ = _timed(label, "archive", lambda: archive_stream(
        work, files, out_dir(p, stream, meta.day), p, opts.keep_work,
        before_clean=lambda: save_state([m for m, _ in items])))
    return archived


def process_stream(stream: Stream, opts: stages.Options, p: config.Paths, day: str) -> List[Path]:
    """Run every stage for one stream; returns the archived paths.

    The run state is saved after the archive succeeded and before the work folder is deleted,
    so a failed save leaves the work folder (and the finished clips) in place.
    """
    label = stream.streamer
    st_path = state.state_file(p, stream.id)
    s = state.load(st_path)
    plan = choose_section(stream, s, opts.section)
    if plan is None:
        print(f"[{label}] nothing new since the last run", flush=True)
        return []
    section, until = plan
    work = p.work / storage.safe_name(stream.id)
    work.mkdir(parents=True, exist_ok=True)
    if stages.cached_section_differs(work, section):
        opts = replace(opts, redo=True)
    meta = archiving.run_meta(work, p, stream, day, opts.redo)

    def save_state(moments: List[Moment]) -> None:
        state.save(st_path, state.advance(s, until, moments), p.archive)

    chosen, seconds = _select(stream, work, section, opts, p, s, label)
    if chosen:
        items, clip_seconds, failed = _make_clips(stream, work, chosen, opts, label, meta)
        if not items:
            raise RuntimeError(f"all {failed} clips failed; work folder kept for a retry")
        notes = {**stages.read_notes(work), "failed_clips": failed}
        return _finish(stream, work, items, {**seconds, **clip_seconds}, opts, p, meta, label, save_state, notes)
    print(f"[{label}] no clips found", flush=True)
    save_state([])
    if not opts.keep_work:
        storage.clean_work(work, p.work)
    return []


def _run_one(process: Callable, stream: Stream, opts: stages.Options, p: config.Paths, day: str) -> bool:
    try:
        archived = process(stream, opts, p, day)
    except Exception as exc:  # one failing stream must not stop the others
        print(f"FAILED {stream.url}: {type(exc).__name__}: {exc}", flush=True)
        return False
    for path in archived:
        print(f"archived {path}", flush=True)
    return True


def _resolve_all(urls: Sequence[str], cookies: Optional[str], resolve: Callable) -> Tuple[List[Stream], bool]:
    """Streams for the URLs, one per stream id (two links to one stream are processed once)."""
    streams, ok = {}, True
    for url in urls:
        try:
            stream = resolve(url, cookies)
        except Exception as exc:  # a bad link must not stop the others
            print(f"FAILED {url}: {type(exc).__name__}: {exc}", flush=True)
            ok = False
            continue
        streams.setdefault(stream.id, stream)
    return list(streams.values()), ok


def _usage_warning(p: config.Paths) -> None:
    try:
        total, _, free = shutil.disk_usage(p.archive)
    except OSError:
        return
    warning = storage.usage_warning(total, free)
    if warning:
        print(warning, flush=True)


def _doctor_ok(checks) -> bool:
    failed = [c for c in checks if not c.ok]
    for c in failed:
        print(f"[FAIL] {c.name} -> {c.fix}", flush=True)
    return not failed


def main(argv: Optional[Sequence[str]] = None, doctor_checks: Callable = doctor.run_all,
         process: Callable = process_stream, finder: Callable = find.find_streams,
         resolve: Callable = stream_from_url) -> int:
    args = parse_args(argv)
    if not _doctor_ok(doctor_checks()):
        return 1
    found = finder(args.streams, args.cookies) if (args.list or args.find or not args.urls) else []
    if args.list:
        for s in found:
            print(f"{s.streamer}  {s.title}  {s.url}")
        return 0
    streams, resolved_ok = _resolve_all([*args.urls, *(s.url for s in found)], args.cookies, resolve)
    p, opts, day = config.paths(), options(args), datetime.now().strftime("%Y-%m-%d")
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        results = list(pool.map(lambda st: _run_one(process, st, opts, p, day), streams))
    _usage_warning(p)
    return 0 if resolved_ok and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
