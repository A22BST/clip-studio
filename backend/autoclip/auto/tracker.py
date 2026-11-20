"""Rebuildable local CSV tracker; no Google Sheet integration."""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .campaign_meta import load_auto_campaign
from .config import AutoConfig
from .store import Store, parse_iso
from .uploadpost import UploadPostClient, UploadPostError

FIELDS = [
    "campaign",
    "rate_per_1k_usd",
    "platform",
    "url",
    "posted_at",
    "title",
    "views",
    "likes",
    "comments",
    "shares",
    "submitted_at",
    "estimated_usd",
    "last_checked",
]


class SheetSink(Protocol):
    """Unimplemented extension point for a future Google Sheet sink."""

    def write_rows(self, rows: list[dict]) -> None: ...


def append_post_rows(store: Store, config: AutoConfig) -> None:
    """Rebuild one row per posted (post, platform), atomically and without duplicates."""
    path = config.tracker_csv()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for post in store.list_posts("posted"):
        clip = store.get_clip(post["clip_id"])
        rate = load_auto_campaign(clip["campaign_key"]).campaign.rate_per_1k_usd
        metrics = store.latest_metrics(post["id"])
        for platform in dict.fromkeys(post["platforms"]):
            metric = metrics.get(platform, {})
            counts = {key: metric.get(key, 0) for key in ("views", "likes", "comments", "shares")}
            rows.append(
                {
                    "campaign": clip["campaign_key"],
                    "rate_per_1k_usd": rate,
                    "platform": platform,
                    "url": post["results"].get(platform, {}).get("url", ""),
                    "posted_at": post["posted_at"],
                    "title": clip["title"],
                    **counts,
                    "submitted_at": post["submitted_at"] or "",
                    "estimated_usd": counts["views"] / 1000 * rate,
                    "last_checked": metric.get("fetched_at", ""),
                }
            )
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent, suffix=".csv", delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        temporary = handle.name
    os.replace(temporary, path)


def pull_views(store: Store, config: AutoConfig, client: UploadPostClient) -> None:
    now = datetime.now(UTC)
    for post in store.list_posts("posted"):
        posted_at = parse_iso(post["posted_at"])
        if (
            not post["request_id"]
            or not posted_at
            or not now - timedelta(days=45) < posted_at <= now
        ):
            continue
        try:
            metrics = client.post_analytics(post["request_id"])
        except UploadPostError:
            continue
        for platform, metric in metrics.items():
            if platform in post["platforms"]:
                store.add_metric(post["id"], platform, **asdict(metric), fetched_at=now)
    append_post_rows(store, config)
