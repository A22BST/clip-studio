"""Auto-throttle, the safety net against account suppression.

* A platform whose last 3 mature posts average below ``drop_ratio`` (20%) of its 7-day average is
  paused for ``pause_hours`` (48) and its daily cap is halved. The reason is logged.
* A removal, strike or copyright claim on ANY platform pauses everything until a human runs
  ``clip-auto resume`` (``report_removal``). Removals cannot be detected without platform APIs,
  so this is called by the CLI (``clip-auto report-removal``) or by anything that learns of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .config import AutoConfig
from .store import Store, parse_iso


def _views(store: Store, post_id: int) -> int:
    return sum(m["views"] for m in store.latest_metrics(post_id).values())


def evaluate(store: Store, config: AutoConfig, now: datetime | None = None) -> list[str]:
    """Run after the daily view pull. Returns the platforms that were throttled."""
    if not config.throttle.enabled:
        return []
    now = now or datetime.now(UTC)
    throttled = []
    posts = [p for p in store.list_posts("posted") if p["posted_at"]]
    for platform in config.post.platforms:
        existing = store.platform_pause_until(platform)
        if existing and existing > now:
            continue
        mine = sorted(
            (p for p in posts if platform in p["platforms"]),
            key=lambda p: parse_iso(p["posted_at"]),
            reverse=True,
        )
        # posts younger than a day have not collected views yet and are ignored
        mature = [p for p in mine if now - parse_iso(p["posted_at"]) >= timedelta(hours=24)]
        week = [p for p in mature if now - parse_iso(p["posted_at"]) <= timedelta(days=7)]
        if len(mature) < 3 or len(week) < 4:
            continue
        recent = sum(_views(store, p["id"]) for p in mature[:3]) / 3
        average = sum(_views(store, p["id"]) for p in week) / len(week)
        if average > 0 and recent < config.throttle.drop_ratio * average:
            until = now + timedelta(hours=config.throttle.pause_hours)
            store.set_platform_pause(platform, until)
            store.set_cap_factor(platform, store.cap_factor(platform) / 2)
            store.log_event(
                "throttle",
                f"{platform}: last-3 average {recent:.0f} < {config.throttle.drop_ratio:.0%} "
                f"of 7-day average {average:.0f}; paused until {until:%F %H:%M} UTC, cap halved",
            )
            throttled.append(platform)
    return throttled


def report_removal(store: Store, platform: str, reason: str, by: str = "cli") -> None:
    """A post was removed / a strike or copyright claim arrived: stop everything."""
    store.set_paused(True, f"{by}: removal/strike on {platform}")
    store.log_event("removal", f"{platform}: {reason[:300]}")
