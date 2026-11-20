"""Ground truth for hype detection: clips that viewers made of the same VOD.

Ahmad has not watched the test streamers, so "7 of my top 10 moments" is replaced by:
the 10 most-viewed viewer clips of the VOD must mostly fall inside the top-15 hype
windows (+/- tolerance). Run hype with ``viewer_clips=None`` for this test, otherwise
the check is circular.

Needs a Twitch app Client ID + secret in ``TWITCH_CLIENT_ID`` / ``TWITCH_CLIENT_SECRET``
(created by Ahmad; never stored in the repo). Clips whose VOD was deleted have no
``vod_offset`` and are skipped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class TwitchApiError(RuntimeError):
    pass


@dataclass
class ViewerClip:
    offset_s: float  # seconds from the start of the VOD
    views: int
    title: str = ""
    duration_s: float = 0.0


def app_token(client_id: str, client_secret: str, *, client: httpx.Client | None = None) -> str:
    http = client or httpx.Client(timeout=30)
    r = http.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
    )
    if r.status_code != 200:
        raise TwitchApiError(f"Could not get a Twitch app token: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


def fetch_viewer_clips(
    vod_id: str, *, client_id: str | None = None, client_secret: str | None = None
) -> list[ViewerClip]:
    """All viewer clips of one VOD (by ``video_id``), most viewed first."""
    client_id = client_id or os.environ.get("TWITCH_CLIENT_ID")
    client_secret = client_secret or os.environ.get("TWITCH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise TwitchApiError(
            "Set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET (Twitch developer app)."
        )
    with httpx.Client(timeout=30) as http:
        headers = {
            "Client-Id": client_id,
            "Authorization": f"Bearer {app_token(client_id, client_secret, client=http)}",
        }

        def get(path: str, **params):
            r = http.get(f"{HELIX}/{path}", params=params, headers=headers)
            if r.status_code != 200:
                raise TwitchApiError(f"{path} failed: {r.status_code} {r.text[:200]}")
            return r.json()

        videos = get("videos", id=vod_id).get("data", [])
        if not videos:
            raise TwitchApiError(f"VOD {vod_id} not found (deleted or private).")
        video = videos[0]
        started = video["created_at"]
        # Twitch clips can only be made while live or from the VOD afterwards: query from the
        # start of the broadcast to 7 days later.
        clips: list[ViewerClip] = []
        cursor = None
        while True:
            params = {
                "broadcaster_id": video["user_id"],
                "started_at": started,
                "first": 100,
            }
            if cursor:
                params["after"] = cursor
            page = get("clips", **params)
            for c in page.get("data", []):
                if str(c.get("video_id")) == str(vod_id) and c.get("vod_offset") is not None:
                    clips.append(
                        ViewerClip(
                            float(c["vod_offset"]),
                            int(c.get("view_count", 0)),
                            c.get("title", ""),
                            float(c.get("duration", 0.0)),
                        )
                    )
            cursor = (page.get("pagination") or {}).get("cursor")
            if not cursor or len(clips) > 2000:
                break
    clips.sort(key=lambda c: c.views, reverse=True)
    return clips


def hit_rate(
    clips: list[ViewerClip],
    windows: list[tuple[float, float]],
    *,
    top_clips: int = 10,
    tolerance_s: float = 30.0,
    offset_s: float = 0.0,
    max_s: float | None = None,
) -> tuple[float, list[tuple[ViewerClip, bool]]]:
    """Share of the ``top_clips`` most-viewed viewer clips inside a hype window (+/- tolerance).

    ``offset_s`` converts VOD time to file time for a trimmed download (pass the trim
    start); ``max_s`` drops clips beyond the downloaded range. Returns (rate, details).
    """
    chosen: list[ViewerClip] = []
    for clip in sorted(clips, key=lambda c: c.views, reverse=True):
        t = clip.offset_s - offset_s
        if t < 0 or (max_s is not None and t > max_s):
            continue
        chosen.append(ViewerClip(t, clip.views, clip.title, clip.duration_s))
        if len(chosen) == top_clips:
            break
    details = [
        (c, any(a - tolerance_s <= c.offset_s <= b + tolerance_s for a, b in windows))
        for c in chosen
    ]
    rate = sum(hit for _, hit in details) / len(details) if details else 0.0
    return rate, details
