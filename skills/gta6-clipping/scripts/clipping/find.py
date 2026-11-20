"""Find recent GTA 6 streams: YouTube search, a watchlist of streamers, optional Twitch top list."""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config, ytdlp
from .models import Stream

SEARCH_QUERY = "ytsearch20:GTA 6 stream"
WATCHLIST_PATH = Path(__file__).resolve().parents[2] / "streamers.txt"
RECENT_HOURS = 36
VODS_PER_STREAMER = 3
TWITCH_TOP_COUNT = 20
HTTP_TIMEOUT_S = 15
GTA_PATTERN = re.compile(r"GTA\s*(?:6|VI)\b", re.IGNORECASE)
PLATFORMS = ("twitch", "youtube")


def parse_watchlist(text: str) -> list:
    """Parse 'platform:name' lines; ignore comments, blanks and invalid lines."""
    entries = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        platform, name = (part.strip() for part in line.split(":", 1))
        if platform.lower() in PLATFORMS and name:
            entries.append((platform.lower(), name))
    return entries


def _entry_timestamp(entry: dict) -> Optional[float]:
    for key in ("timestamp", "release_timestamp"):
        value = entry.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    date = entry.get("upload_date")
    if isinstance(date, str):
        try:
            return datetime.strptime(date, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None
    return None


def is_gta_recent(entry: dict, now: float, hours: int = RECENT_HOURS) -> bool:
    """True if the title mentions GTA 6/VI and the entry is at most `hours` old."""
    title = entry.get("title")
    if not isinstance(title, str) or not GTA_PATTERN.search(title):
        return False
    ts = _entry_timestamp(entry)
    return ts is not None and 0 <= now - ts <= hours * 3600


def rank(streams: list, views: dict) -> list:
    """Highest-view stream per streamer, sorted by views descending."""
    best = {}
    for s in streams:
        if s.streamer not in best or views.get(s.id, 0) > views.get(best[s.streamer].id, 0):
            best[s.streamer] = s
    return sorted(best.values(), key=lambda s: views.get(s.id, 0), reverse=True)


def _stream_from_entry(entry: dict, platform: str, streamer: str) -> Optional[Stream]:
    vid, url = entry.get("id"), entry.get("webpage_url") or entry.get("url")
    if not vid or not url:
        return None
    return Stream(
        id=f"{platform}-{vid}", url=url, platform=platform,
        streamer=entry.get("uploader") or entry.get("channel") or streamer,
        title=entry.get("title") or "", duration=entry.get("duration"),
        is_live=bool(entry.get("is_live")),
    )


def _collect(url: str, platform: str, streamer: str, cookies, extra: tuple, now: float) -> list:
    try:
        data = ytdlp.info(url, cookies, extra)
    except RuntimeError as exc:
        print(f"skip {url}: {exc}", file=sys.stderr)
        return []
    found = []
    for entry in data.get("entries") or [data]:
        if not entry or not is_gta_recent(entry, now):
            continue
        stream = _stream_from_entry(entry, platform, streamer)
        if stream:
            found.append((stream, int(entry.get("view_count") or 0)))
    return found


def _watchlist_urls() -> list:
    try:
        text = WATCHLIST_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"watchlist unreadable: {exc}", file=sys.stderr)
        return []
    urls = []
    for platform, name in parse_watchlist(text):
        if platform == "twitch":
            urls.append((f"https://www.twitch.tv/{name}/videos?filter=archives", platform, name))
        else:
            urls.append((f"https://www.youtube.com/{name}/streams", platform, name))
    return urls


def _read_env(path: Path) -> dict:
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        key, sep, val = line.strip().partition("=")
        if sep and not key.startswith("#"):
            values[key.strip()] = val.strip().strip("\"'")
    return values


def _twitch_json(url: str, headers: dict, data: Optional[bytes] = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 (fixed https hosts)
        return json.load(resp)


def _twitch_top_logins(client_id: str, secret: str) -> list:
    token = _twitch_json(
        "https://id.twitch.tv/oauth2/token", {},
        urllib.parse.urlencode({"client_id": client_id, "client_secret": secret,
                                "grant_type": "client_credentials"}).encode(),
    )["access_token"]
    headers = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
    games = _twitch_json("https://api.twitch.tv/helix/games?name=Grand%20Theft%20Auto%20VI", headers)
    if not games.get("data"):
        return []
    query = urllib.parse.urlencode({"game_id": games["data"][0]["id"], "first": TWITCH_TOP_COUNT})
    live = _twitch_json(f"https://api.twitch.tv/helix/streams?{query}", headers)
    return [s["user_login"] for s in live.get("data", []) if s.get("user_login")]


def _twitch_top_urls(env_file: Path) -> list:
    env = _read_env(env_file)
    client_id, secret = env.get("TWITCH_CLIENT_ID"), env.get("TWITCH_CLIENT_SECRET")
    if not client_id or not secret:
        return []
    try:
        logins = _twitch_top_logins(client_id, secret)
    except (OSError, KeyError, ValueError) as exc:
        print(f"twitch top list unavailable: {type(exc).__name__}", file=sys.stderr)
        return []
    return [(f"https://www.twitch.tv/{login}", "twitch", login) for login in logins]


def find_streams(limit: int, cookies: Optional[str]) -> list:
    """Return up to `limit` recent GTA 6 streams, biggest first, one per streamer."""
    now = time.time()
    env_file = config.paths().home / "gta6-clips" / ".env"
    sources = [(SEARCH_QUERY, "youtube", "", ("--playlist-end", "20"))]
    sources += [(u, p, n, ("--playlist-end", str(VODS_PER_STREAMER)))
                for u, p, n in _watchlist_urls()]
    sources += [(u, p, n, ()) for u, p, n in _twitch_top_urls(env_file)]
    streams, views = [], {}
    for url, platform, name, extra in sources:
        for stream, count in _collect(url, platform, name, cookies, extra, now):
            streams.append(stream)
            views[stream.id] = count
    return rank(streams, views)[:limit]
