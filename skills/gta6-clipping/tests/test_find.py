from datetime import datetime, timezone

from clipping import find
from clipping.models import Stream

NOW = 1_800_000_000.0
HOUR = 3600


def make_stream(sid, streamer):
    return Stream(id=sid, url=f"https://x/{sid}", platform="youtube", streamer=streamer,
                  title="GTA 6", duration=None, is_live=False)


def test_parse_watchlist_skips_comments_and_bad_lines():
    text = "# header\n\ntwitch:kaicenat\n  youtube:@IShowSpeed  \nnocolon\nfoo:bar\ntwitch:\n# twitch:x\n"
    assert find.parse_watchlist(text) == [("twitch", "kaicenat"), ("youtube", "@IShowSpeed")]


def test_is_gta_recent_requires_gta_in_title():
    recent = {"timestamp": NOW - HOUR}
    assert find.is_gta_recent({"title": "GTA VI first look", **recent}, NOW)
    assert find.is_gta_recent({"title": "gta6 live", **recent}, NOW)
    assert find.is_gta_recent({"title": "GTAVI hype", **recent}, NOW)
    assert not find.is_gta_recent({"title": "GTA 5 roleplay", **recent}, NOW)
    assert not find.is_gta_recent({"title": "Minecraft", **recent}, NOW)


def test_is_gta_recent_rejects_old():
    assert not find.is_gta_recent({"title": "GTA 6", "timestamp": NOW - 37 * HOUR}, NOW)
    assert find.is_gta_recent({"title": "GTA 6", "release_timestamp": NOW - 35 * HOUR}, NOW)
    assert not find.is_gta_recent({"title": "GTA 6"}, NOW)


def test_is_gta_recent_upload_date_fallback():
    noon = datetime(2027, 1, 15, 12, tzinfo=timezone.utc).timestamp()
    assert find.is_gta_recent({"title": "GTA 6", "upload_date": "20270115"}, noon)
    assert not find.is_gta_recent({"title": "GTA 6", "upload_date": "garbage"}, NOW)


def test_rank_one_per_streamer():
    a1, a2, b = make_stream("a1", "A"), make_stream("a2", "A"), make_stream("b", "B")
    ranked = find.rank([a1, a2, b], {"a1": 10, "a2": 500, "b": 100})
    assert ranked == [a2, b]


def test_rank_missing_views_count_as_zero():
    a, b = make_stream("a", "A"), make_stream("b", "B")
    assert find.rank([a, b], {"b": 1}) == [b, a]


def test_ytdlp_base_args_adds_cookies_only_when_set():
    from clipping import ytdlp
    assert "--cookies-from-browser" not in ytdlp.base_args(None)
    args = ytdlp.base_args("chrome")
    assert args[args.index("--js-runtimes") + 1] == "node"
    assert args[args.index("--cookies-from-browser") + 1] == "chrome"
