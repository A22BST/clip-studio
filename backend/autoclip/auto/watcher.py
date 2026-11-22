"""Discover Twitch and YouTube streams and queue slices without downloading media."""

from __future__ import annotations

import logging
import math
import re
import time
import unicodedata
from collections.abc import Iterable
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
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


def _plain_title(title: str) -> str:
    """Keep metadata output free of pictographs, including on legacy consoles."""
    return "".join(c for c in title if unicodedata.category(c) not in {"So", "Cs"}
                   and c not in {"\u200d", "\ufe0f", "\u20e3"})


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


def _get(client: httpx.Client, endpoint: str, *, paginate: bool = False, **params: str) -> list[dict[str, Any]]:
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
        data = response.json()
        rows = data["data"]
        cursor = (data.get("pagination") or {}).get("cursor")
        if paginate and cursor:
            rows += _get(client, endpoint, paginate=True, **{**params, "after": cursor})
        return rows
    return []  # Both attempts either return data or raise.


def _youtube_vods(streamer: str, since: date | None = None) -> list[dict[str, Any]]:
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
        "proxy": "",
        "lazy_playlist": True,
    }
    if since:
        options.pop("playlistend")
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
        # Backfill filters VOD publication dates; a marathon may start before midnight
        # and only become a published archive the next day. Watch keeps source time.
        timestamp = (
            entry.get("timestamp") or entry.get("release_timestamp")
            if since else entry.get("release_timestamp") or entry.get("timestamp")
        )
        duration = entry.get("duration")
        if timestamp is None:
            continue
        if since and datetime.fromtimestamp(timestamp, UTC).date() < since:
            break
        if (duration is None or duration <= 0) and entry.get("live_status") != "is_live":
            continue  # Never queue an unbounded live download or guess the source date.
        vods.append(
            {
                "id": entry["id"],
                "title": entry.get("title") or "",
                "created_at": datetime.fromtimestamp(timestamp, UTC).isoformat(),
                "duration": f"{int(duration or 0)}s",
                "url": f"https://www.youtube.com/watch?v={entry['id']}",
                "is_live": entry.get("live_status") in {"is_live", "post_live"},
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
                        if vod.get("is_live") and (platform == "youtube" or config.watch.wait_until_offline):
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


def backfill_ranges(duration: int, size: int, known, platform: str, vod_id: str):
    """Subtract existing footage before splitting, so changing slice sizes leaves no holes."""
    cursor = 0
    covered = sorted((int(j["start_s"]), int(j["end_s"] or duration)) for j in known
                     if j["platform"] == platform and j["vod_id"] == vod_id
                     and j["state"] != "skipped")
    for lo, hi in [*covered, (duration, duration)]:
        stop = min(duration, lo)
        while cursor < stop:
            end = min(cursor + size, stop)
            yield cursor, end
            cursor = end
        cursor = max(cursor, min(duration, hi))


def backfill(
    store: Store | None, config: AutoConfig, campaign: AutoCampaign, *,
    since: date | None = None, max_slices: int | None = None, slice_hours: float = 2.5,
    per_day_hours: float | None = None, dry_run: bool = False,
    client: httpx.Client | None = None, emit=print,
    existing_jobs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """List and enqueue historical slices. Metadata only, including in non-dry runs.

    Backfill settings live in the campaign sidecar's ``backfill`` section. CLI daily
    overrides are persisted in store metadata; no source-age restriction applies here.
    """
    if not math.isfinite(slice_hours) or slice_hours <= 0:
        raise ValueError("slice-hours must be positive and finite")
    if max_slices is not None and max_slices < 1:
        raise ValueError("max-slices must be positive")
    if per_day_hours is not None and (not math.isfinite(per_day_hours) or per_day_hours <= 0):
        raise ValueError("per-day-hours must be positive and finite")
    since = since or campaign.meta.starts_at or date(2026, 11, 19)
    if campaign.meta.starts_at:
        since = max(since, campaign.meta.starts_at)
    if campaign.meta.platform not in {"youtube", "twitch"}:
        raise ValueError("Backfill supports Twitch and YouTube only")
    live, reason = campaign.is_live()
    if not live:
        emit(f"Skipped campaign {campaign.key}: {reason}")
        return []
    if not dry_run and not disk_ok(config)[0]:
        emit("Backfill paused: disk guard")
        return []
    vods = []
    with nullcontext(client) if client is not None else httpx.Client(timeout=30, trust_env=False) as http:
        for streamer in campaign.meta.streamers:
            if campaign.meta.platform == "youtube":
                entries = _youtube_vods(streamer, since=since)
            else:
                users = _get(http, "users", login=streamer)
                if not users:
                    emit(f"No Twitch user found for configured streamer {streamer}")
                    continue
                streams = _get(http, "streams", user_login=streamer)
                live_ids = {s["id"] for s in streams}
                entries = _get(http, "videos", user_id=users[0]["id"], type="archive",
                               first="100", paginate=True)
                entries = [{**v, "is_live": bool(v.get("stream_id") in live_ids)} for v in entries]
            for vod in entries:
                created = parse_iso(vod["created_at"])
                if not created or created.date() < since:
                    continue
                if vod.get("is_live"):
                    emit(f"Skipped live stream {vod['id']}: {_plain_title(vod['title'])}")
                    continue
                game = str(vod.get("game_name") or vod.get("game") or "")
                chapters = vod.get("chapters") or []
                gta = re.search(r"\bGTA\b|Grand\s+Theft\s+Auto", vod["title"], re.I)
                gta = gta or game.casefold() == "grand theft auto vi" or any(
                    str(c.get("game_name") or c.get("game") or c.get("title") or "").casefold()
                    == "grand theft auto vi" for c in chapters if isinstance(c, dict)
                )
                if not gta and campaign.key != "dylan-page-marathon":
                    continue
                duration = parse_duration(vod["duration"])
                if duration > 0:
                    vods.append({**vod, "streamer": streamer, "duration_s": duration})
    vods.sort(key=lambda v: parse_iso(v["created_at"]), reverse=True)
    known = list(existing_jobs if existing_jobs is not None else store.list_jobs() if store else [])
    plans = []
    for vod in vods:
        slices = []
        size = max(1, int(slice_hours * 3600))
        for start, end in backfill_ranges(vod["duration_s"], size, known,
                                          campaign.meta.platform, vod["id"]):
            if max_slices is not None and len(plans) >= max_slices:
                break
            fields = dict(campaign_key=campaign.key, platform=campaign.meta.platform,
                          vod_id=vod["id"], streamer=vod["streamer"], title=vod["title"],
                          vod_created_at=vod["created_at"], url=vod["url"], start_s=start, end_s=end)
            plans.append(fields)
            slices.append(f"{start}-{end}s")
            known.append({**fields, "state": "queued"})
            if not dry_run:
                assert store is not None
                # Insert and mark atomically so a tick cannot claim an unmarked slice.
                from .store import now_iso
                with store._conn() as con:
                    cols = {**fields, "created_at": now_iso(), "updated_at": now_iso()}
                    cur = con.execute(
                        f"INSERT OR IGNORE INTO jobs({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
                        tuple(cols.values()),
                    )
                    if cur.rowcount:
                        con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                                    (f"backfill:job:{cur.lastrowid}", "1"))
        if slices:
            emit(f"{vod['id']} | {_plain_title(vod['title'])} | {vod['created_at']} | {vod['duration_s']}s")
            emit("  " + ("Would enqueue: " if dry_run else "Enqueued: ") + ", ".join(slices))
    if not dry_run and store and per_day_hours is not None:
        store.set_meta(f"backfill:daily_limit:{campaign.key}", str(per_day_hours))
    emit(f"{'Would enqueue' if dry_run else 'Enqueued'} {len(plans)} slices for {campaign.key} since {since}.")
    return plans
