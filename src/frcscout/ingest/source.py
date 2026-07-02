"""Resolve an input (local file, direct URL, or YouTube page URL) into
something cv2.VideoCapture can open.

YouTube pages are resolved with yt-dlp's Python API to a direct media/manifest
URL (HLS for live, progressive/DASH mp4 for VODs). yt-dlp is an optional
dependency: `pip install -e ".[ingest]"`.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .errors import IngestError

_BOT_BLOCK_HINT = (
    " — YouTube is bot-blocking this server's IP (common for cloud hosts). "
    "Fixes: (1) upload the VOD file instead of a URL — most reliable; "
    "(2) set the YTDLP_COOKIES env var to the contents of a YouTube "
    "cookies.txt exported from a logged-in browser "
    "(see yt-dlp's 'exporting YouTube cookies' FAQ); "
    "(3) use a direct media URL."
)


def _cookie_file() -> str | None:
    """Cookies for yt-dlp: a file path (YTDLP_COOKIES_FILE) or the cookies.txt
    content itself (YTDLP_COOKIES — handy on PaaS where env vars are all you
    have; written to a temp file)."""
    path = os.environ.get("YTDLP_COOKIES_FILE")
    if path:
        return path
    content = os.environ.get("YTDLP_COOKIES")
    if content:
        temp = Path(tempfile.gettempdir()) / "frcscout_yt_cookies.txt"
        temp.write_text(content)
        return str(temp)
    return None

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
# Direct media the capture backend can open without help.
_DIRECT_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m3u8", ".webm"}


@dataclass(frozen=True)
class SourceInfo:
    """A playable source. `location` is a local path or direct media URL."""
    location: str
    is_live: bool
    kind: str            # "file" | "direct-url" | "youtube"
    title: str | None = None


def _resolve_youtube(url: str, prefer_height: int = 720) -> SourceInfo:
    try:
        import yt_dlp
    except ImportError as exc:
        raise IngestError(
            "yt-dlp is required for YouTube URLs: pip install -e '.[ingest]'"
        ) from exc

    # Prefer a single muxed (or video-only) stream near prefer_height — the
    # pipeline needs video only, and 720p is plenty for detection/OCR.
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": f"best[height<={prefer_height}]/bestvideo[height<={prefer_height}]/best",
    }
    cookies = _cookie_file()
    if cookies:
        opts["cookiefile"] = cookies
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        message = str(exc)
        hint = _BOT_BLOCK_HINT if ("not a bot" in message
                                   or "Sign in to confirm" in message) else ""
        raise IngestError(f"could not resolve {url}: {message}{hint}") from exc
    if info.get("_type") == "playlist":
        raise IngestError("got a playlist URL; pass a single video/stream URL")
    location = info.get("url")
    if not location:
        raise IngestError(f"yt-dlp returned no playable URL for {url}")
    return SourceInfo(
        location=location,
        is_live=bool(info.get("is_live")),
        kind="youtube",
        title=info.get("title"),
    )


def resolve_source(source: str, prefer_height: int = 720) -> SourceInfo:
    path = Path(source)
    if path.exists():
        return SourceInfo(location=str(path), is_live=False, kind="file", title=path.name)

    parsed = urlparse(source)
    if parsed.scheme in ("http", "https", "rtmp", "rtsp"):
        host = (parsed.hostname or "").lower()
        if host in _YOUTUBE_HOSTS or host.endswith(".youtube.com"):
            return _resolve_youtube(source, prefer_height)
        if Path(parsed.path).suffix.lower() in _DIRECT_SUFFIXES or parsed.scheme in ("rtmp", "rtsp"):
            return SourceInfo(location=source, is_live=False, kind="direct-url")
        # Unknown page URL: let yt-dlp try — it supports hundreds of sites
        # (Twitch, etc.), and fails with a clear error if it can't.
        return _resolve_youtube(source, prefer_height)

    raise IngestError(f"source {source!r} is neither an existing file nor a URL")
