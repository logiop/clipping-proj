"""JSON schemas for `claude -p --json-schema` replies (standard JSON Schema 2020-12)."""
import json
from pathlib import Path

EVENTS_PATH = Path(__file__).resolve().parents[2] / "config" / "events.json"
CATEGORIES = ("first_reaction", "discovery", "reaction", "funny", "take")
FALLBACK_EVENT = "other"


def load_events(path: Path = EVENTS_PATH) -> tuple:
    events = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(events, list) or FALLBACK_EVENT not in events:
        raise ValueError(f"{path} must be a list of event keys including '{FALLBACK_EVENT}'")
    return tuple(events)


EVENTS = load_events()

_STR = {"type": "string"}

MOMENTS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["moments"],
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["start", "end", "score", "category", "event",
                             "hook", "caption", "hashtags", "reason"],
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "score": {"type": "integer", "minimum": 1, "maximum": 100},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "event": {"type": "string", "enum": list(EVENTS)},
                    "hook": _STR,
                    "caption": _STR,
                    "hashtags": {"type": "array", "items": _STR},
                    "reason": _STR,
                    "flags": {"type": "array", "items": _STR},
                },
            },
        }
    },
}

LOOK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "gameplay", "why"],
                "properties": {
                    "index": {"type": "integer"},
                    "gameplay": {"type": "boolean"},
                    "why": _STR,
                },
            },
        }
    },
}
