"""Discover Twitch and YouTube streams and queue slices without downloading media."""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Iterable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from . import secrets
from .campaign_meta import AutoCampaign, load_all_auto_campaigns
from .config import AutoConfig
from .diskguard import disk_ok
from .store import Store, parse_iso

log = logging.getLogger(__name__)
_tokens: dict[str, tuple[str, float]] = {}
_HELIX = "https://api.twitch.tv/helix"


def parse_duration(value: str) -> int:
    """Convert Twitch's optional hours/minutes/seconds components to seconds."""
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", value)
    if not match or not value:
        raise ValueError("Invalid Twitch duration")
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _token(client: httpx.Client, client_id: str, refresh: bool = False) -> str:
    cached = _tokens.get(client_id)
    if not refresh and cached and cached[1] > time.monotonic():
        return cached[0]
    secret = secrets.get_secret(secrets.TWITCH_CLIENT_SECRET)
    if not secret:
        raise ValueError("Missing Twitch credentials")
    response = client.post(
        "https://id.twitch.tv/oauth2/token",
        data={"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"},
    )
    response.raise_for_status()
    data = response.json()
    token = data["access_token"]
    _tokens[client_id] = (token, time.monotonic() + max(0, float(data["expires_in"]) - 60))
    return token


def _get(client: httpx.Client, endpoint: str, **params: str) -> list[dict[str, Any]]:
    client_id = secrets.get_secret(secrets.TWITCH_CLIENT_ID)
    if not client_id:
        raise ValueError("Missing Twitch credentials")
    for attempt in range(2):
        token = _token(client, client_id, refresh=attempt == 1)
        response = client.get(
            f"{_HELIX}/{endpoint}",
            params=params,
            headers={"Client-ID": client_id, "Authorization": f"Bearer {token}"},
        )
        if response.status_code == 401 and attempt == 0:
            _tokens.pop(client_id, None)
            continue
        response.raise_for_status()
        return response.json()["data"]
    return []  # Both attempts either return data or raise.


def _youtube_vods(streamer: str) -> list[dict[str, Any]]:
    """Read the latest five streams from the exact configured YouTube handle."""
    import yt_dlp

    if not re.fullmatch(r"@[A-Za-z0-9_.-]+", streamer):
        raise ValueError("YouTube streamers must be explicit @handles")
    options = {
        "skip_download": True,
        "extract_flat": False,
        "playlistend": 5,
        "quiet": True,
        "no_warnings": True,
        "ignore_no_formats_error": True,
        "socket_timeout": 15,
        "retries": 0,
        "extractor_retries": 0,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(f"https://www.youtube.com/{streamer}/streams", download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise ValueError("YouTube metadata discovery failed") from exc
    if not data:
        raise ValueError("YouTube returned no metadata")
    vods = []
    for entry in data.get("entries") or []:
        if not entry or entry.get("live_status") not in {"is_live", "was_live", "post_live"}:
            continue
        timestamp = entry.get("release_timestamp") or entry.get("timestamp")
        duration = entry.get("duration")
        if timestamp is None or duration is None or duration <= 0:
            continue  # Never queue an unbounded live download or guess the source date.
        vods.append(
            {
                "id": entry["id"],
                "title": entry.get("title") or "",
                "created_at": datetime.fromtimestamp(timestamp, UTC).isoformat(),
                "duration": f"{int(duration)}s",
                "url": f"https://www.youtube.com/watch?v={entry['id']}",
                "is_live": entry.get("live_status") == "is_live",
            }
        )
    return vods


def scan(
    store: Store,
    config: AutoConfig,
    campaigns: Iterable[AutoCampaign] | None = None,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> list[int]:
    """Return newly queued job IDs; baseline rows are skipped and never returned.

    A failed baseline remains incomplete until a later successful discovery pass.
    The caller retains ownership of an injected HTTP client.
    """
    allowed, reason = disk_ok(config)
    if not allowed:
        log.info("Watcher paused: %s", reason)
        return []
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    campaigns = load_all_auto_campaigns() if campaigns is None else campaigns
    baseline = config.watch.baseline_on_first_run and not store.get_meta("watch_baseline_done")
    queued: list[int] = []
    failed = False
    scanned = False
    with nullcontext(client) if client is not None else httpx.Client(timeout=30) as http:
        for campaign in campaigns:
            if not campaign.is_live(now)[0]:
                continue
            platform = campaign.meta.platform
            if platform not in {"twitch", "youtube"}:
                log.info("Skipping unsupported watcher platform for campaign %s", campaign.key)
                continue
            for streamer in campaign.meta.streamers:
                scanned = True
                try:
                    if platform == "youtube":
                        vods = _youtube_vods(streamer)
                    else:
                        users = _get(http, "users", login=streamer)
                        if not users:
                            continue
                        vods = _get(
                            http, "videos", user_id=users[0]["id"], type="archive", first="5"
                        )
                        if (
                            not baseline
                            and config.watch.wait_until_offline
                            and _get(http, "streams", user_login=streamer)
                        ):
                            continue
                    for vod in vods:
                        if store.vod_known(platform, vod["id"]):
                            continue
                        fields = {
                            "campaign_key": campaign.key,
                            "platform": platform,
                            "vod_id": vod["id"],
                            "streamer": streamer,
                            "title": vod["title"],
                            "vod_created_at": vod["created_at"],
                            "url": vod["url"],
                        }
                        if baseline:
                            store.add_job(**fields, state="skipped")
                            continue
                        created = parse_iso(vod["created_at"])
                        if not baseline and config.watch.wait_until_offline and vod.get("is_live"):
                            continue
                        if (
                            created
                            and campaign.meta.starts_at
                            and created.date() < campaign.meta.starts_at
                        ):
                            continue
                        if created is None or now - created > timedelta(
                            hours=config.watch.max_vod_age_hours
                        ):
                            continue
                        if not disk_ok(config)[0]:
                            return queued
                        duration = parse_duration(vod["duration"])
                        size = config.watch.slice_hours * 3600
                        slices = (
                            [(0, duration if platform == "youtube" else 0)]
                            if duration <= size
                            else [
                                (index * size, min((index + 1) * size, duration))
                                for index in range(
                                    min(math.ceil(duration / size), config.watch.max_slices_per_vod)
                                )
                            ]
                        )
                        for start, end in slices:
                            job_id = store.add_job(**fields, start_s=start, end_s=end)
                            if job_id is not None:
                                queued.append(job_id)
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    # Exception text, HTTP bodies and request URLs may contain credentials.
                    log.warning(
                        "%s discovery failed for streamer %s; continuing", platform, streamer
                    )
                    failed = True
    if scanned and not failed:
        store.set_meta("watch_baseline_done", "1")
    return queued
