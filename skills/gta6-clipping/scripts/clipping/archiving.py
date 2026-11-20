"""Archive bookkeeping for one stream run: destination folder, clip numbering that continues
after clips already on the stick, a per-run stamp, and a manifest of files already archived."""
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import storage
from .config import Paths
from .models import Stream

MANIFEST = "archived.json"
RUN_META = "run.json"
STAMP_FORMAT = "%H%M%S"
_CLIP_NAME = re.compile(r"^(\d+)\.mp4$")


@dataclass(frozen=True)
class RunMeta:
    day: str     # day folder the run archives into (kept on resume, even past midnight)
    stamp: str   # run start time, HHMMSS: names POST_<stamp>.md etc.
    first: int   # number of the run's first clip


def out_dir(p: Paths, stream: Stream, day: str) -> Path:
    return p.out / day / f"{storage.safe_name(stream.streamer)}__{storage.safe_name(stream.title)}"


def clip_name(meta: RunMeta, index: int) -> str:
    return f"{meta.first + index:02d}"


def next_clip_number(dest_dir: Path, root: Path) -> int:
    """1 + the highest NN.mp4 already in dest_dir (1 when there is none)."""
    target = storage.safe_path(root, dest_dir)
    if not target.is_dir():
        return 1
    numbers = [int(m.group(1)) for f in target.iterdir() if (m := _CLIP_NAME.match(f.name))]
    return max(numbers, default=0) + 1


def read_manifest(work_dir: Path) -> Tuple[str, ...]:
    path = work_dir / MANIFEST
    if not path.exists():
        return ()
    return tuple(json.loads(path.read_text(encoding="utf-8")))


def _write_manifest(work_dir: Path, names: Tuple[str, ...]) -> None:
    (work_dir / MANIFEST).write_text(json.dumps(list(names), indent=2), encoding="utf-8")


def run_meta(work: Path, p: Paths, stream: Stream, day: str, redo: bool,
             now: Optional[Callable[[], datetime]] = None) -> RunMeta:
    """The run's day, stamp and first clip number; reused on resume, new (with an empty manifest) on redo."""
    path = work / RUN_META
    if path.exists() and not redo:
        return RunMeta(**json.loads(path.read_text(encoding="utf-8")))
    started = (now or datetime.now)()
    meta = RunMeta(day=day, stamp=started.strftime(STAMP_FORMAT),
                   first=next_clip_number(out_dir(p, stream, day), p.archive))
    work.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
    _write_manifest(work, ())
    return meta


def archive_stream(work_dir: Path, files: List[Path], dest_dir: Path, p: Paths, keep_work: bool,
                   archive: Optional[Callable] = None, clean: Optional[Callable] = None,
                   before_clean: Optional[Callable[[], None]] = None) -> List[Path]:
    """Copy every file to dest_dir on the stick, recording each in the work folder's manifest
    so an interrupted archive resumes where it stopped. When all succeeded: before_clean()
    (e.g. save the run state), then delete work_dir unless keep_work. Any error propagates
    and leaves work_dir untouched."""
    archive = archive or storage.archive_file
    clean = clean or storage.clean_work
    done = read_manifest(work_dir)
    archived = []
    for f in files:
        dest = dest_dir / f.name
        if f.name not in done:
            archive(f, dest, p.archive)
            done = (*done, f.name)
            _write_manifest(work_dir, done)
        archived.append(storage.safe_path(p.archive, dest))
    if before_clean is not None:
        before_clean()
    if not keep_work:
        clean(work_dir, p.work)
    return archived
