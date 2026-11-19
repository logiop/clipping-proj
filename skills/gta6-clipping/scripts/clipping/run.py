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

from . import config, doctor, find, post, stages, state, storage, ytdlp
from .layout import FORCED_VALUES
from .models import Moment, Stream

DEFAULT_STREAMS = 3
DEFAULT_PARALLEL = 2
DEFAULT_PICK_PARALLEL = 4
PLATFORMS = ("youtube", "twitch")


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


def build_parser() -> argparse.ArgumentParser:
    settings = config.load()
    ap = argparse.ArgumentParser(prog="gta6clip", description="Vertical GTA 6 clips from streams, archived to the stick.")
    ap.add_argument("urls", nargs="*", metavar="URL", help="stream/VOD links (none: find streams)")
    ap.add_argument("--find", action="store_true", help="also find recent GTA 6 streams")
    ap.add_argument("--list", action="store_true", help="only list found streams")
    ap.add_argument("--streams", type=int, default=DEFAULT_STREAMS, help="streams to find")
    ap.add_argument("--clips", type=int, default=settings.clips_per_stream, help="clips per stream")
    ap.add_argument("--section", type=_section_arg, help="only A-B of the stream (s, m:ss or h:mm:ss)")
    ap.add_argument("--cookies", metavar="BROWSER", help="browser to read cookies from")
    ap.add_argument("--layout", choices=FORCED_VALUES, default="auto")
    ap.add_argument("--model", default=settings.model, help="Claude model for picking and checking")
    ap.add_argument("--fast", action="store_true", help="hardware encoder")
    ap.add_argument("--redo", action="store_true", help="ignore saved stage files")
    ap.add_argument("--keep-work", action="store_true", help="keep the Mac work folder after archiving")
    ap.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL, help="streams at a time")
    ap.add_argument("--pick-parallel", type=int, default=DEFAULT_PICK_PARALLEL, help="Claude pick calls at a time")
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


def out_dir(p: config.Paths, stream: Stream, day: str) -> Path:
    return p.out / day / f"{storage.safe_name(stream.streamer)}__{storage.safe_name(stream.title)}"


def _already_archived(src: Path, dest: Path, root: Path) -> bool:
    target = storage.safe_path(root, dest)
    return target.exists() and target.stat().st_size == src.stat().st_size


def archive_stream(work_dir: Path, files: List[Path], dest_dir: Path, p: config.Paths, keep_work: bool,
                   archive: Callable = storage.archive_file, clean: Callable = storage.clean_work) -> List[Path]:
    """Copy every file to dest_dir on the stick; then (unless keep_work) delete work_dir.

    A file already archived with the same size (an interrupted earlier run) is not copied again.
    Any error propagates and leaves work_dir untouched.
    """
    archived = []
    for f in files:
        dest = dest_dir / f.name
        if _already_archived(f, dest, p.archive):
            archived.append(storage.safe_path(p.archive, dest))
            continue
        archived.append(archive(f, dest, p.archive))
    if not keep_work:
        clean(work_dir, p.work)
    return archived


def choose_section(stream: Stream, s: state.RunState,
                   explicit: stages.Section) -> Optional[Tuple[stages.Section, float]]:
    """(audio section or None for all, processed-until) — or None when there is nothing new."""
    if explicit is not None:
        return explicit, explicit[1]
    duration = float(stream.duration or 0.0)
    if stream.is_live:
        nxt = state.next_section(s, duration)
        return (nxt, nxt[1]) if nxt else None
    if s.processed_until and s.processed_until >= duration:
        return None
    return None, duration


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


def _make_clips(stream, work, chosen, opts, label) -> Tuple[List[Tuple[Moment, Path]], dict]:
    items, totals = [], {}
    for i, m in enumerate(chosen):
        moment, out, timings = stages.clip_stage(stream, work, f"{i + 1:02d}", m, opts)
        items.append((moment, out))
        totals = {k: totals.get(k, 0.0) + timings.get(k, 0.0) for k in {*totals, *timings}}
    for stage in ("fetch", "layout", "captions", "render"):
        _log(label, stage, totals.get(stage, 0.0))
    return items, totals


def _finish(stream, work, items, seconds, opts, p, day, label) -> List[Path]:
    posted = post.write(work / "out", stream, [(m, Path(out.name)) for m, out in items], seconds)
    files = [out for _, out in items] + posted
    archived, _ = _timed(label, "archive", lambda: archive_stream(
        work, files, out_dir(p, stream, day), p, opts.keep_work))
    return archived


def process_stream(url: str, opts: stages.Options, p: config.Paths, day: str) -> List[Path]:
    """Run every stage for one stream; returns the archived paths."""
    stream = stream_from_url(url, opts.cookies)
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
    chosen, seconds = _select(stream, work, section, opts, p, s, label)
    if not chosen:
        print(f"[{label}] no clips found", flush=True)
        archived = []
        if not opts.keep_work:
            storage.clean_work(work, p.work)
    else:
        items, clip_seconds = _make_clips(stream, work, chosen, opts, label)
        archived = _finish(stream, work, items, {**seconds, **clip_seconds}, opts, p, day, label)
        chosen = [m for m, _ in items]
    state.save(st_path, state.advance(s, until, chosen), p.archive)
    return archived


def _run_one(process: Callable, url: str, opts: stages.Options, p: config.Paths, day: str) -> bool:
    try:
        archived = process(url, opts, p, day)
    except Exception as exc:  # one failing stream must not stop the others
        print(f"FAILED {url}: {type(exc).__name__}: {exc}", flush=True)
        return False
    for path in archived:
        print(f"archived {path}", flush=True)
    return True


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
         process: Callable = process_stream, finder: Callable = find.find_streams) -> int:
    args = parse_args(argv)
    if not _doctor_ok(doctor_checks()):
        return 1
    found = finder(args.streams, args.cookies) if (args.list or args.find or not args.urls) else []
    if args.list:
        for s in found:
            print(f"{s.streamer}  {s.title}  {s.url}")
        return 0
    urls = list(dict.fromkeys([*args.urls, *(s.url for s in found)]))
    p, opts, day = config.paths(), options(args), datetime.now().strftime("%Y-%m-%d")
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        results = list(pool.map(lambda u: _run_one(process, u, opts, p, day), urls))
    _usage_warning(p)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
