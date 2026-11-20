"""Word-by-word captions: Whisper on the finished clip, ASS output, language check."""
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Sequence, Tuple

from .listen import transcript
from .listen.transcript import Word

CAPTION_MODEL = "base"
DEFAULT_FONT = "Arial Black"  # Montserrat ExtraBold when installed would be nicer; Arial Black always resolves on macOS
DEFAULT_FONT_SIZE = 84
DEFAULT_CAPTION_Y = 1400  # baseline, lower third of a 1080x1920 frame
MIN_LANGUAGE_PROB = 0.6
MIN_MEAN_WORD_PROB = 0.5
WHITE = "&HFFFFFF&"
YELLOW = "&H00FFFF&"


@dataclass(frozen=True)
class CaptionStyle:
    font: str = DEFAULT_FONT
    size: int = DEFAULT_FONT_SIZE
    outline: int = 6
    shadow: int = 0
    primary: str = WHITE
    highlight: str = YELLOW
    outline_colour: str = "&H000000&"
    bold: bool = True


def group(words: Sequence[Word], max_words: int = 3, max_gap: float = 0.6) -> List[List[Word]]:
    """Split words into captions of at most max_words, breaking on silences over max_gap."""
    groups: List[List[Word]] = []
    current: List[Word] = []
    for word in words:
        if current and (len(current) >= max_words or word.start - current[-1].end > max_gap):
            groups.append(current)
            current = []
        current = [*current, word]
    if current:
        groups.append(current)
    return groups


def _timestamp(seconds: float) -> str:
    total_cs = int(round(max(seconds, 0.0) * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    return f"{total_s // 3600}:{total_s // 60 % 60:02d}:{total_s % 60:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _style_colour(colour: str) -> str:
    """Override-tag colour (&HBBGGRR&) to style-line colour (&H00BBGGRR)."""
    return "&H00" + colour[2:].rstrip("&")


def _colour_tag(colour: str) -> str:
    return "{\\c" + colour + "}"


def _line(group_words: Sequence[Word], active: int, style: CaptionStyle, x: int, y: int) -> str:
    parts = []
    for i, word in enumerate(group_words):
        text = _escape(word.text)
        if i == active:
            parts.append(_colour_tag(style.highlight) + text + _colour_tag(style.primary))
        else:
            parts.append(text)
    word = group_words[active]
    # Each word owns the window from its start to the next word's start (or its own end)
    end = group_words[active + 1].start if active + 1 < len(group_words) else word.end
    return (f"Dialogue: 0,{_timestamp(word.start)},{_timestamp(end)},Caption,,0,0,0,,"
            f"{{\\pos({x},{y})}}{' '.join(parts)}")


def to_ass(groups: Sequence[Sequence[Word]], style: CaptionStyle, width: int = 1080,
           height: int = 1920, y: int = DEFAULT_CAPTION_Y) -> str:
    """Complete ASS document; one Dialogue per word with that word highlighted.

    y is the baseline (bottom edge) of the caption in PlayRes pixels; text is centred on width.
    """
    bold = -1 if style.bold else 0
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{style.font},{style.size},{_style_colour(style.primary)},"
        f"&H00000000,{_style_colour(style.outline_colour)},&H00000000,"
        f"{bold},0,0,0,100,100,0,0,1,{style.outline},{style.shadow},2,40,40,40,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    x = width // 2
    events = [_line(g, i, style, x, y) for g in groups if g for i in range(len(g))]
    return "\n".join(header + events) + "\n"


def language_flags(language: str, prob: float, words: Sequence[Word]) -> Tuple[str, ...]:
    """Review flags: non_english (also when language is unknown or prob is NaN), low_confidence."""
    flags: Tuple[str, ...] = ()
    if language != "en" or math.isnan(prob) or prob < MIN_LANGUAGE_PROB:
        flags += ("non_english",)
    if not words or sum(w.prob for w in words) / len(words) < MIN_MEAN_WORD_PROB:
        flags += ("low_confidence",)
    return flags


def _shifted(words: Sequence[Word], offset: float) -> List[Word]:
    moved = [replace(w, start=max(w.start + offset, 0.0), end=w.end + offset) for w in words]
    return [w for w in moved if w.end > 0]


def make(clip_audio: Path, offset: float) -> Tuple[str, Tuple[str, ...]]:
    """Transcribe the clip audio only; return (ass_text, flags).

    offset is ADDED to every word time (seconds): pass 0 when clip_audio starts at the clip
    start, a negative value to pull captions earlier, a positive one to delay them.
    Words that end up before time 0 are dropped.
    """
    _, words, language, prob = transcript.whisper(clip_audio, CAPTION_MODEL, True)
    flags = language_flags(language, prob, words)
    ass = to_ass(group(_shifted(words, offset)), CaptionStyle(), y=DEFAULT_CAPTION_Y)
    return ass, flags
