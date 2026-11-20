"""Safe-posting schedule: per-platform daily caps that ramp with account age, spacing with
jitter, staggered platforms, best QA first, expiry of clips that wait too long.

Defaults (all in config ``post``): 1 / 2 / 3 posts per platform per day in weeks 1 / 2 / 3+, at
least 4 h between posts on one platform (+ up to 30 min jitter), the same clip 1-2 h apart on its
platforms, clips that cannot be scheduled within 48 h expire. ``throttle.py`` can pause a platform
and halve its cap.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .campaign_meta import load_auto_campaign
from .config import AutoConfig
from .store import Store, now_iso, parse_iso

LIVE = ("queued", "posting", "posted")


def account_start(store: Store, config: AutoConfig, now: datetime) -> datetime:
    if config.post.start_date:
        day = datetime.fromisoformat(config.post.start_date)
        return day if day.tzinfo else day.replace(tzinfo=UTC)
    first = store.get_meta("first_scheduled_at")
    if first:
        return parse_iso(first) or now
    store.set_meta("first_scheduled_at", now_iso(now))
    return now


def daily_cap(store: Store, config: AutoConfig, platform: str, now: datetime) -> int:
    """Posts allowed today on one platform: ramp by account week, scaled by the throttle."""
    caps = config.post.per_platform_daily_caps or [1]
    week = max(0, (now - account_start(store, config, now)).days // 7)
    base = caps[min(week, len(caps) - 1)]
    return max(1, int(base * store.cap_factor(platform)))


def _window(config: AutoConfig) -> tuple[int, int]:
    """Posting window in local minutes of the day: first to last configured slot."""
    minutes = [int(h) * 60 + int(m) for h, m in (s.split(":") for s in config.post.slots)]
    return min(minutes), max(minutes)


def platform_slot(
    store: Store,
    config: AutoConfig,
    platform: str,
    earliest: datetime,
    rng: random.Random,
) -> datetime:
    tz = ZoneInfo(config.post.timezone)
    posts = [p for p in store.list_posts() if p["status"] in LIVE and platform in p["platforms"]]
    last = max((parse_iso(p["scheduled_for"]) for p in posts), default=None)
    gap = timedelta(hours=config.post.min_gap_hours_per_platform)
    jitter = timedelta(minutes=rng.uniform(0, 1) * config.post.jitter_minutes)
    candidate = earliest
    if last:
        candidate = max(candidate, last + gap + jitter)  # jitter only ever adds spacing
    until = store.platform_pause_until(platform)
    if until:
        candidate = max(candidate, until)
    lo, hi = _window(config)
    for _ in range(400):
        local = candidate.astimezone(tz)
        minute = local.hour * 60 + local.minute
        if minute < lo:
            candidate = local.replace(hour=lo // 60, minute=lo % 60, second=0, microsecond=0)
            candidate = candidate.astimezone(UTC) + jitter
        elif minute > hi:
            nxt = (local + timedelta(days=1)).replace(
                hour=lo // 60, minute=lo % 60, second=0, microsecond=0
            )
            candidate = nxt.astimezone(UTC) + jitter
        day = candidate.astimezone(tz).date()
        cap = daily_cap(store, config, platform, candidate)
        same_day = [p for p in posts if parse_iso(p["scheduled_for"]).astimezone(tz).date() == day]
        if len(same_day) < cap:
            return candidate
        candidate = datetime.combine(
            day + timedelta(days=1), datetime.min.time(), tzinfo=tz
        ).astimezone(UTC)
    raise RuntimeError("no free posting slot found")


def schedule_clip(
    store: Store,
    config: AutoConfig,
    clip: dict,
    platforms: list[str],
    earliest: datetime,
    rng: random.Random,
) -> list[int]:
    """One post row per platform, the platforms staggered 1-2 h apart."""
    ids: list[int] = []
    start = earliest
    order = list(platforms)
    rng.shuffle(order)  # the platform that goes first varies
    for platform in order:
        when = platform_slot(store, config, platform, start, rng)
        ids.append(store.enqueue_post(clip["id"], when, [platform]))
        lo, hi = config.post.stagger_minutes
        start = when + timedelta(minutes=rng.uniform(lo, hi))
    return ids


def schedule_approved(
    store: Store,
    config: AutoConfig,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> list[int]:
    """Queue approved clips, best QA first. Clips that would wait past the expiry are expired."""
    now = now or datetime.now(UTC)
    rng = rng or random.Random()
    queued = {p["clip_id"] for p in store.list_posts() if p["status"] in LIVE}
    created: list[int] = []
    ready = [c for c in store.list_clips("approved") if c["id"] not in queued]
    for clip in sorted(ready, key=lambda c: (-c["qa_score"], c["id"])):
        approved_at = parse_iso(clip["approved_at"]) or now
        earliest = now
        if clip["approved_by"] == "auto:level2":
            earliest = max(now, approved_at + timedelta(minutes=config.auto_approve.delay_minutes))
        campaign = load_auto_campaign(clip["campaign_key"]).campaign
        platforms = [p for p in config.post.platforms if p in campaign.platforms]
        if not platforms:
            store.log_event("schedule_skipped", f"clip {clip['id']}: no shared platforms")
            continue
        deadline = approved_at + timedelta(hours=config.post.queue_expiry_hours)
        ids = schedule_clip(store, config, clip, platforms, earliest, rng)
        last = max(parse_iso(store.get_post(i)["scheduled_for"]) for i in ids)
        if last > deadline:  # would wait too long: do not post it at all
            for i in ids:
                store.cancel_post(i, "expired in queue")
            store.set_clip_status(clip["id"], "expired")
            store.log_event("expired", f"clip {clip['id']} would post after {deadline:%F %H:%M}")
            continue
        created += ids
    return created


def expire_stale(store: Store, config: AutoConfig, now: datetime | None = None) -> int:
    """Approved or pending clips that sat unposted past the expiry are dropped."""
    now = now or datetime.now(UTC)
    limit = timedelta(hours=config.post.queue_expiry_hours)
    live = {p["clip_id"] for p in store.list_posts() if p["status"] in LIVE}
    n = 0
    for status in ("approved", "pending_approval"):
        for clip in store.list_clips(status):
            made = parse_iso(clip["created_at"]) or now
            if clip["id"] not in live and now - made > limit:
                store.set_clip_status(clip["id"], "expired")
                n += 1
    return n
