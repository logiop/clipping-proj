"""Paths and settings. Pure computation: never touches the archive volume."""
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_ARCHIVE = "/Volumes/KINGSTOM/Cartella di Claude"
FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FAT32_MAX_FILE_BYTES = 4 * 1024**3 - 1

EVENT_KEYS = (
    "first_drive",
    "first_wanted_level",
    "first_police_chase",
    "first_mission",
    "first_mission_fail",
    "first_death",
    "map_reaction",
    "character_reaction",
    "graphics_reaction",
    "funny_fail",
    "other",
)


@dataclass(frozen=True)
class Paths:
    home: Path
    work: Path
    archive: Path
    out: Path
    state: Path
    hf_home: Path
    models: Path
    venv: Path


@dataclass(frozen=True)
class Settings:
    clips_per_stream: int = 3
    min_clip_s: int = 15
    max_clip_s: int = 60
    min_gap_s: int = 60
    model: str = "sonnet"
    loudnorm: str = "loudnorm=I=-14:TP=-1.5:LRA=11"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    fast_codec: str = "h264_videotoolbox"
    x264_crf: int = 20
    audio_bitrate: str = "192k"
    min_mac_free_bytes: int = 5_000_000_000
    min_stick_free_bytes: int = 2_000_000_000
    stick_warn_ratio: float = 0.8
    fat32_max_file_bytes: int = FAT32_MAX_FILE_BYTES
    event_keys: tuple = EVENT_KEYS


def paths(env: Optional[Mapping[str, str]] = None) -> Paths:
    env = env if env is not None else {}
    home = Path(env.get("HOME", str(Path.home())))
    archive = Path(env.get("CLIP_ARCHIVE") or DEFAULT_ARCHIVE)
    out = archive / "gta6-clips"
    private = home / ".gta6-clipping"
    return Paths(
        home=home,
        work=home / "gta6-clips" / "work",
        archive=archive,
        out=out,
        state=out / "state",
        hf_home=archive / "models",
        models=private / "models",
        venv=private / "venv",
    )


def load(overrides: Optional[dict] = None) -> Settings:
    return replace(Settings(), **(overrides or {}))


def ffmpeg_bin() -> str:
    if Path(FFMPEG_FULL).exists():
        return FFMPEG_FULL
    return shutil.which("ffmpeg") or "ffmpeg"
