"""Transcript: platform captions first, Whisper as fallback."""
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .. import ytdlp
from ..models import Stream

CAPTION_TIMEOUT_S = 30
FALLBACK_MODEL = "tiny"
_CUE = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})")
_TAG = re.compile(r"<[^>]*>")


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str
    prob: float


def _seconds(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_vtt(text: str) -> List[Segment]:
    """Parse WebVTT; lines repeated from the previous cue (rolling auto-captions) are dropped."""
    segments: List[Segment] = []
    previous: List[str] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        idx = next((i for i, ln in enumerate(lines) if _CUE.search(ln)), None)
        if idx is None:
            continue
        m = _CUE.search(lines[idx])
        start = _seconds(*m.group(1, 2, 3, 4))
        end = _seconds(*m.group(5, 6, 7, 8))
        cleaned = [_TAG.sub("", ln).strip() for ln in lines[idx + 1:]]
        cleaned = [ln for ln in cleaned if ln]
        fresh = [ln for ln in cleaned if ln not in previous]
        previous = cleaned
        if fresh:
            segments.append(Segment(start, end, " ".join(fresh)))
    return segments


def find_caption_url(info: dict) -> Optional[str]:
    """URL of an English VTT track (manual subtitles first, then automatic captions)."""
    for group in ("subtitles", "automatic_captions"):
        tracks = info.get(group) or {}
        for lang in sorted(tracks, key=lambda k: (k != "en", k)):
            if lang != "en" and not lang.startswith("en-"):
                continue
            for fmt in tracks[lang]:
                if fmt.get("ext") == "vtt" and fmt.get("url"):
                    return fmt["url"]
    return None


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=CAPTION_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8", errors="replace")


def whisper(audio: Path, model: str, words: bool) -> Tuple[List[Segment], List[Word], str, float]:
    """Transcribe with mlx_whisper if importable, else faster-whisper int8.

    The model cache comes from the HF_HOME environment variable (set by the launcher).
    The mlx path does not report a language probability: it returns NaN, meaning
    "unknown - treat as needs review", and language "" when mlx gives none.
    """
    try:
        import mlx_whisper
    except ImportError:
        return _whisper_faster(audio, model, words)
    result = mlx_whisper.transcribe(str(audio), path_or_hf_repo=f"mlx-community/whisper-{model}-mlx",
                                    word_timestamps=words)
    segs = [Segment(s["start"], s["end"], s["text"].strip()) for s in result["segments"]]
    word_list = [Word(w["start"], w["end"], w["word"].strip(), w.get("probability", 1.0))
                 for s in result["segments"] for w in s.get("words", [])]
    return segs, word_list, result.get("language") or "", float("nan")


def _whisper_faster(audio: Path, model: str, words: bool):
    from faster_whisper import WhisperModel
    engine = WhisperModel(model, device="cpu", compute_type="int8")
    raw, info = engine.transcribe(str(audio), word_timestamps=words)
    segs, word_list = [], []
    for s in raw:
        segs.append(Segment(s.start, s.end, s.text.strip()))
        word_list.extend(Word(w.start, w.end, w.word.strip(), w.probability) for w in (s.words or []))
    return segs, word_list, info.language, info.language_probability


def get(stream: Stream, audio: Path, cookies: Optional[str] = None,
        section: Optional[Tuple[float, float]] = None) -> List[Segment]:
    """Platform English captions if available, otherwise Whisper `tiny` on the audio.

    Times are stream time. With `section` (the audio covers only [start, end] of the stream),
    platform captions are limited to the section and Whisper times are shifted by its start.
    """
    try:
        url = find_caption_url(ytdlp.info(stream.url, cookies))
        segments = parse_vtt(_fetch_text(url)) if url else []
    except (RuntimeError, OSError) as exc:
        print(f"caption lookup failed ({type(exc).__name__}); falling back to Whisper tiny", file=sys.stderr)
        segments = []
    if section is not None:
        segments = [s for s in segments if s.end > section[0] and s.start < section[1]]
    if segments:
        return segments
    offset = section[0] if section is not None else 0.0
    return [Segment(s.start + offset, s.end + offset, s.text) for s in whisper(audio, FALLBACK_MODEL, False)[0]]
