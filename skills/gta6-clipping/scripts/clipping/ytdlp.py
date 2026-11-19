"""Thin wrappers around the yt-dlp CLI."""
import json
import subprocess
from typing import Optional

TIMEOUT_S = 180


def base_args(cookies: Optional[str]) -> list:
    args = ["yt-dlp", "--js-runtimes", "node", "--no-warnings"]
    if cookies:
        args += ["--cookies-from-browser", cookies]
    return args


def info(url: str, cookies: Optional[str], extra: tuple = ()) -> dict:
    """Return yt-dlp's JSON metadata for a URL (no download). Raises RuntimeError on failure."""
    cmd = base_args(cookies) + ["-J", "--skip-download", *extra, url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"yt-dlp timed out for {url}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed for {url}: {proc.stderr.strip()[-300:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"yt-dlp returned invalid JSON for {url}") from exc
