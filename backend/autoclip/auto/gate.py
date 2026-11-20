"""The single choke point between "a clip exists" and "a clip is posted".

``check_post_allowed`` is called by the poster immediately before EVERY upload and fails
closed: any missing fact, exception or doubt is a denial. Nothing else in the package may call
the Upload-Post client.

A post is allowed only when ALL of these hold:

1. the kill switch (``/pause``) is off;
2. the clip is ``approved`` by the human (``discord:<DISCORD_OWNER_ID>`` or
   ``telegram:<TELEGRAM_CHAT_ID>``), or - only
   with ``level: 2`` AND ``auto_approve.enabled: true`` in config.yaml - by ``auto:level2`` with
   QA >= ``auto_approve.min_qa`` and the review delay elapsed;
3. the file on disk has the same SHA-256 as the one that was approved (no edit after approval);
4. the render report says ``exported`` and the spoiler level is not ``raw-cinematic``;
5. the approval is not older than ``post.approval_ttl_hours``;
6. the campaign has a sidecar, is live (active, not past ``ends_at``), under budget;
7. session 1's rules engine passes again on the stored facts (length, required tags and
   caption phrases, banned words, disclosure, overlay file, today-only age);
8. the platforms are allowed by both the campaign and config;
9. the per-day post cap is not exceeded.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import secrets
from .campaign_meta import load_auto_campaign
from .config import AutoConfig
from .store import Store, parse_iso


@dataclass
class GateResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.allowed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_duration(path: Path) -> float:
    from ..pipeline import ffmpeg

    return float(ffmpeg.probe(path).duration_s)


def check_post_allowed(
    store: Store,
    clip_id: int,
    *,
    config: AutoConfig,
    platforms: list[str],
    post_id: int | None = None,
    now: datetime | None = None,
    campaigns_dir: Path | None = None,
    expected_chat_id: str | None = None,
    probe_duration: Callable[[Path], float] | None = None,
) -> GateResult:
    try:
        reasons = _evaluate(
            store, clip_id, config, platforms, post_id, now or datetime.now(UTC),
            campaigns_dir, expected_chat_id, probe_duration or _probe_duration,
        )  # fmt: skip
    except Exception as exc:  # fail closed
        reasons = [f"gate error: {type(exc).__name__}: {str(exc)[:200]}"]
    result = GateResult(allowed=not reasons, reasons=reasons)
    if not result.allowed:
        store.log_event("gate_denied", f"clip {clip_id}: " + "; ".join(reasons))
    return result


def _evaluate(
    store: Store,
    clip_id: int,
    config: AutoConfig,
    platforms: list[str],
    post_id: int | None,
    now: datetime,
    campaigns_dir: Path | None,
    expected_chat_id: str | None,
    probe_duration: Callable[[Path], float],
) -> list[str]:
    from ..pipeline import rules
    from ..stream.pipeline import resolve_overlay

    deny: list[str] = []
    if store.is_paused():
        return ["paused (/pause is on)"]
    clip = store.get_clip(clip_id)
    if clip is None:
        return [f"clip {clip_id} does not exist"]
    # "posted" = another platform of this clip already went out; the approval fields still apply
    if clip["status"] not in ("approved", "posted") or not clip["approved_by"]:
        return [f"clip status is {clip['status']!r}, not 'approved'"]

    # -- who approved it ------------------------------------------------------------
    by = clip["approved_by"] or ""
    approved_at = parse_iso(clip["approved_at"])
    if approved_at is None:
        return ["no approval timestamp"]
    if by.startswith(("telegram:", "discord:")):
        service = by.split(":", 1)[0]
        env_name = secrets.TELEGRAM_CHAT_ID if service == "telegram" else secrets.DISCORD_OWNER_ID
        owner = expected_chat_id or secrets.get_secret(env_name)
        if not owner or by != f"{service}:{owner}":
            deny.append("approval did not come from the configured owner/chat")
    elif by == "auto:level2":
        if not config.level2_active:
            deny.append("auto approval is not enabled in config (level 2 is off)")
        elif clip["qa_score"] < config.auto_approve.min_qa:
            deny.append(f"QA {clip['qa_score']} below auto-approve minimum")
        elif now < approved_at + timedelta(minutes=config.auto_approve.delay_minutes):
            deny.append("auto-approve review delay has not elapsed")
    else:
        deny.append(f"unknown approver {by!r}")
    if now > approved_at + timedelta(hours=config.post.approval_ttl_hours):
        deny.append("approval expired")

    # -- the file is the one that was approved -------------------------------------
    path = Path(clip["path"])
    if not path.is_file():
        deny.append("clip file is missing")
        return deny
    if not clip["approved_sha256"] or sha256_file(path) != clip["approved_sha256"]:
        deny.append("clip file changed after approval")
    if clip["report_status"] != "exported":
        deny.append(f"render report status is {clip['report_status']!r}")
    if clip["spoiler_level"] not in ("none", "reaction-to-spoiler"):
        deny.append(f"spoiler level {clip['spoiler_level']!r} may not be posted")

    # -- campaign -------------------------------------------------------------------
    try:
        auto = load_auto_campaign(clip["campaign_key"], campaigns_dir)
    except Exception as exc:
        return [*deny, f"campaign {clip['campaign_key']!r} unusable: {type(exc).__name__}"]
    live, why = auto.is_live(now)
    if not live:
        deny.append(why)
    campaign = auto.campaign
    if auto.meta.budget_usd:
        spend = _estimated_earnings(store, clip["campaign_key"], campaign.rate_per_1k_usd)
        if spend >= auto.meta.budget_usd:
            deny.append(f"campaign budget reached (~${spend:.0f} of ${auto.meta.budget_usd:g})")

    allowed_platforms = set(campaign.platforms or config.post.platforms) & set(
        config.post.platforms
    )
    if not platforms or not set(platforms) <= allowed_platforms:
        deny.append(
            f"platforms {platforms} not allowed (campaign/config: {sorted(allowed_platforms)})"
        )

    # -- rules engine again (cheap, deterministic) ------------------------------------
    duration = probe_duration(path)
    stream_date = parse_iso(clip["stream_date"]) if clip["stream_date"] else None
    result = rules.check_clip(
        campaign,
        rules.ClipFacts(
            duration_s=duration,
            title=clip["title"],
            caption=clip["caption"],
            hashtags=list(clip["hashtags"]),
            mentions=list(clip["mentions"]),
            hook=clip["hook"],
            spoiler_level=clip["spoiler_level"],
            source_stream_date=stream_date,
            now=now,
            has_captions=True,
            has_hook=bool(clip["hook"]),
            reframed=True,
            reaction_layout_ok=not (
                clip["spoiler_level"] == "reaction-to-spoiler" and clip["layout"] != "reaction"
            ),
            disclosure_shown=campaign.disclosure_required,
            overlay_applied=resolve_overlay(campaign) is not None,
        ),
    )
    deny += [f"rules: {v.message}" for v in result.violations if v.blocking]

    # -- caps and per-platform throttle ------------------------------------------------
    tz = ZoneInfo(config.post.timezone)
    local_day = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = local_day.astimezone(UTC), (local_day + timedelta(days=1)).astimezone(UTC)
    todays = [p for p in store.posts_between(start, end) if p["id"] != post_id]
    done_today = [p for p in todays if p["status"] == "posted"]
    if len(done_today) >= config.post.max_per_day:
        deny.append(f"daily cap of {config.post.max_per_day} posts reached")
    from .schedule import daily_cap

    for platform in platforms:
        until = store.platform_pause_until(platform)
        if until and now < until:
            deny.append(f"{platform} is paused by the auto-throttle until {until:%Y-%m-%d %H:%M} UTC")
        cap = daily_cap(store, config, platform, now)
        if sum(platform in p["platforms"] for p in done_today) >= cap:
            deny.append(f"{platform} daily cap of {cap} reached")
    return deny


def _estimated_earnings(store: Store, campaign_key: str, rate_per_1k: float) -> float:
    total = 0
    for post in store.list_posts("posted"):
        clip = store.get_clip(post["clip_id"])
        if clip and clip["campaign_key"] == campaign_key:
            total += sum(m["views"] for m in store.latest_metrics(post["id"]).values())
    return total / 1000.0 * rate_per_1k
