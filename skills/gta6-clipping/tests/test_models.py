import json
from pathlib import Path

import jsonschema
import pytest

from clipping import config, models, schemas

EVENTS_PATH = Path(__file__).resolve().parents[1] / "config" / "events.json"


def make_dict(**over):
    base = {
        "start": 100.0, "end": 130.0, "score": 80, "category": "funny",
        "event": "first_drive", "hook": "h", "caption": "c",
        "hashtags": ["gta6"], "reason": "r",
    }
    return {**base, **over}


def test_moment_outside_chunk_is_none():
    assert models.moment_from_dict(make_dict(start=700, end=730), 0, 600) is None


def test_moment_clamps_length():
    m = models.moment_from_dict(make_dict(start=100, end=190), 0, 600)
    assert (m.start, m.end) == (100, 160)


def test_moment_end_clamped_to_chunk():
    m = models.moment_from_dict(make_dict(start=580, end=620), 0, 600)
    assert (m.start, m.end) == (580, 600)


def test_unknown_event_becomes_other():
    m = models.moment_from_dict(make_dict(event="made_up"), 0, 600)
    assert m.event == "other"


def test_short_moment_extended_symmetrically():
    m = models.moment_from_dict(make_dict(start=100, end=105), 0, 600)
    assert (m.start, m.end) == (95, 110)
    assert m.end - m.start == config.Settings().min_clip_s


def test_short_moment_at_chunk_start_shifts_remainder():
    m = models.moment_from_dict(make_dict(start=2, end=7), 0, 600)
    assert (m.start, m.end) == (0, 15)


def test_short_moment_at_chunk_end_shifts_remainder():
    m = models.moment_from_dict(make_dict(start=593, end=598), 0, 600)
    assert (m.start, m.end) == (585, 600)


def test_chunk_shorter_than_min_is_none():
    assert models.moment_from_dict(make_dict(start=2, end=6), 0, 10) is None


@pytest.mark.parametrize("over", [
    {"score": 0}, {"score": 101}, {"score": "x"}, {"score": True},
    {"category": "nope"}, {"start": "a"}, {"end": 50}, {"hook": 5},
    {"hashtags": "gta"}, {"hashtags": [1]}, {"flags": "x"},
])
def test_invalid_fields_are_none(over):
    assert models.moment_from_dict(make_dict(**over), 0, 600) is None


def test_missing_field_is_none():
    d = make_dict()
    del d["reason"]
    assert models.moment_from_dict(d, 0, 600) is None


def test_non_dict_is_none():
    assert models.moment_from_dict("x", 0, 600) is None


def test_moment_is_frozen_and_input_not_mutated():
    d = make_dict()
    snapshot = json.dumps(d, sort_keys=True)
    m = models.moment_from_dict(d, 0, 600)
    assert json.dumps(d, sort_keys=True) == snapshot
    with pytest.raises(Exception):
        m.start = 1


def test_roundtrip_json():
    m = models.moment_from_dict(make_dict(flags=["a"]), 0, 600)
    s = models.Stream("id", "u", "twitch", "who", "t", None, True)
    assert models.from_json(models.Moment, models.to_json(m)) == m
    assert models.from_json(models.Stream, models.to_json(s)) == s
    assert isinstance(models.from_json(models.Moment, models.to_json(m)).hashtags, tuple)


def test_events_json_matches_config_and_schema():
    events = json.loads(EVENTS_PATH.read_text())
    assert tuple(events) == config.EVENT_KEYS
    item = schemas.MOMENTS_SCHEMA["properties"]["moments"]["items"]
    assert item["properties"]["event"]["enum"] == events


def test_moments_schema_validates():
    jsonschema.Draft202012Validator.check_schema(schemas.MOMENTS_SCHEMA)
    jsonschema.validate({"moments": [make_dict()]}, schemas.MOMENTS_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"moments": [make_dict(score=0)]}, schemas.MOMENTS_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"moments": [make_dict(extra=1)]}, schemas.MOMENTS_SCHEMA)


def test_look_schema_validates():
    jsonschema.Draft202012Validator.check_schema(schemas.LOOK_SCHEMA)
    jsonschema.validate({"verdicts": [{"index": 0, "gameplay": True, "why": "x"}]}, schemas.LOOK_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"verdicts": [{"index": 0}]}, schemas.LOOK_SCHEMA)


@pytest.mark.parametrize("over", [{"end": float("inf")}, {"end": float("nan")}, {"start": float("nan")},
                                  {"start": float("-inf")}, {"score": float("inf")}, {"score": float("nan")}])
def test_non_finite_numbers_are_none(over):
    assert models.moment_from_dict(make_dict(**over), 0, 600) is None
