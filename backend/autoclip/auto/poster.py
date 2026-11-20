"""Scheduling and the gated, atomic posting workflow."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import gate
from .campaign_meta import load_auto_campaign
from .config import AutoConfig
from .notify import Button, Notifier
from .preview import make_preview
from .publisher import MANUAL_URL, split_platforms
from .store import Store, parse_iso
from .uploadpost import UploadPostClient, UploadPostError


def next_slot(store: Store, config: AutoConfig, now: datetime) -> datetime:
    if not config.post.slots:
        raise ValueError("No posting slots configured")
    tz = ZoneInfo(config.post.timezone)
    posts = [p for p in store.list_posts() if p["status"] in ("queued", "posting", "posted")]
    latest = max((parse_iso(p["scheduled_for"]) for p in posts), default=None)
    earliest = now.astimezone(UTC)
    if latest:
        earliest = max(earliest, latest + timedelta(minutes=config.post.min_gap_minutes))
    day = earliest.astimezone(tz).date()
    while True:
        count = sum(parse_iso(p["scheduled_for"]).astimezone(tz).date() == day for p in posts)
        if count < config.post.max_per_day:
            candidates = set()
            for slot in config.post.slots:
                hour, minute = map(int, slot.split(":"))
                for fold in (0, 1):
                    local = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(
                        hour=hour, minute=minute, fold=fold
                    )
                    utc = local.astimezone(UTC)
                    # Skip nonexistent spring-forward times.
                    if utc.astimezone(tz).replace(fold=fold) == local and utc >= earliest:
                        candidates.add(utc)
            if candidates:
                return min(candidates)
        day += timedelta(days=1)


def schedule_approved(
    store: Store,
    config: AutoConfig,
    now: datetime | None = None,
) -> list[int]:
    now = now or datetime.now(UTC)
    live = {
        p["clip_id"] for p in store.list_posts() if p["status"] in ("queued", "posting", "posted")
    }
    scheduled = []
    for clip in store.list_clips("approved"):
        if clip["id"] in live:
            continue
        campaign = load_auto_campaign(clip["campaign_key"]).campaign
        platforms = [p for p in config.post.platforms if p in campaign.platforms]
        if not platforms:
            store.log_event("schedule_skipped", f"clip {clip['id']}: no shared platforms")
            continue
        earliest = now
        if clip["approved_by"] == "auto:level2":
            earliest = max(
                now,
                parse_iso(clip["approved_at"])
                + timedelta(minutes=config.auto_approve.delay_minutes),
            )
        scheduled.append(
            store.enqueue_post(clip["id"], next_slot(store, config, earliest), platforms)
        )
    return scheduled


def _buttons(post_id, auto):
    rows = []
    if auto.meta.submit_url:
        rows.append([Button("Open campaign page", url=auto.meta.submit_url)])
    rows.append([Button("Submitted", callback_data=f"s:{post_id}")])
    return rows


def _merge(results, payload, platforms):
    rows = payload if isinstance(payload, list) else payload.get("results", [])
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict) or row.get("platform") not in platforms:
            continue
        platform = row["platform"]
        old = results.get(platform, {})
        skipped = row.get("skip_reason") == "profile_platform_not_configured"
        results[platform] = {
            "url": row.get("post_url") or row.get("url") or old.get("url", ""),
            "success": None if skipped else row.get("success", old.get("success")),
            "message": row.get("skip_reason") or row.get("message") or old.get("message", ""),
            "skipped": skipped or old.get("skipped", False),
        }


def _complete(results, platforms):
    return all(
        p in results
        and (
            results[p].get("url") or results[p].get("skipped") or results[p].get("success") is False
        )
        for p in platforms
    )


def _save_request(store, post_id, request_id, results):
    # Store has no public update-post method; persist before polling for crash recovery.
    with store._conn() as con:
        con.execute(
            "UPDATE posts SET request_id=?, results=? WHERE id=?",
            (request_id, json.dumps(results), post_id),
        )


def _poll(client, request_id, results, platforms, sleep):
    started = time.monotonic()
    for attempt in range(17):
        if _complete(results, platforms):
            break
        try:
            payload = client.status(request_id)
            _merge(results, payload, platforms)
            if isinstance(payload, dict) and payload.get("status") == "failed":
                for platform in platforms:
                    if not results.get(platform, {}).get("url"):
                        results[platform] = {
                            "url": "",
                            "success": False,
                            "message": "Upload failed",
                        }
        except UploadPostError:
            pass  # A known request is never re-uploaded, even on status transport errors.
        if _complete(results, platforms) or attempt == 16 or time.monotonic() - started >= 240:
            break
        sleep(15)
    return results


def _announce(notifier, post, auto):
    deadline = parse_iso(post["submit_deadline"])
    links = [
        f"{p}: {r.get('url') or r.get('message') or 'URL pending'}"
        for p, r in post["results"].items()
    ]
    text = "Posted. SUBMIT TO THE CAMPAIGN NOW: deadline "
    text += f"{deadline:%H:%M} ({auto.campaign.submit_deadline_min} min) UTC"
    notifier.send_text(text + "\n" + "\n".join(links), _buttons(post["id"], auto))


def _send_hand_post(notifier, clip, manual, auto) -> None:
    """The platforms the API cannot post: send the file + caption so Ahmad can post by hand."""
    tags = " ".join("#" + h.lstrip("#") for h in clip["hashtags"])
    caption = chr(10).join(
        [
            f"POST BY HAND on {', '.join(manual)}: upload this clip and use this text.",
            clip["caption"],
            tags,
            f"Full-quality file: {clip['path']}",
        ]
    )
    limit = getattr(notifier, "max_upload_bytes", 45 * 1024 * 1024)
    try:
        shown = make_preview(
            Path(clip["path"]),
            clip["approved_sha256"] or "x" * 16,
            profile=getattr(notifier, "preview_profile", "telegram"),
            limit_bytes=limit,
        )
        notifier.send_video(shown, caption)
    except Exception:
        notifier.send_text(caption)


def refresh_urls(store: Store, client: UploadPostClient, notifier: Notifier) -> None:
    for post in store.list_posts("posted"):
        if not post["request_id"] or _complete(post["results"], post["platforms"]):
            continue
        results = {p: dict(r) for p, r in post["results"].items()}
        with suppress(UploadPostError):
            _merge(results, client.status(post["request_id"]), post["platforms"])
        if not _complete(results, post["platforms"]):
            with suppress(UploadPostError):
                _merge(results, client.history(post["request_id"]), post["platforms"])
        new_links = [
            r["url"]
            for p, r in results.items()
            if r.get("url") and not post["results"].get(p, {}).get("url")
        ]
        if results != post["results"]:
            _save_request(store, post["id"], post["request_id"], results)
        if new_links:
            notifier.send_text("Post links available:\n" + "\n".join(new_links))


def post_due(
    store: Store,
    config: AutoConfig,
    notifier: Notifier,
    client: UploadPostClient | None = None,
    now: datetime | None = None,
    campaigns_dir: Path | None = None,
    gate_kwargs: dict[str, Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[int]:
    now = now or datetime.now(UTC)
    client = client or UploadPostClient(
        base_url=config.upload_post.base_url,
        profile=config.upload_post.profile,
        config=config.upload_post,
    )
    refresh_urls(store, client, notifier)
    finished = []
    # Recover uploads whose process stopped after persisting the request ID.
    recovery = [p for p in store.list_posts("posting") if p["request_id"]]
    for post in [*recovery, *store.due_posts(now)]:
        post_id, clip_id = post["id"], post["clip_id"]
        recovering = post in recovery
        if not recovering:
            if not store.claim_post(post_id):
                continue
            try:
                decision = gate.check_post_allowed(
                    store,
                    clip_id,
                    config=config,
                    platforms=post["platforms"],
                    post_id=post_id,
                    now=now,
                    campaigns_dir=campaigns_dir,
                    **(gate_kwargs or {}),
                )
                reasons = (decision.reasons or ["gate denied"]) if not decision.allowed else []
            except Exception:
                reasons = ["gate error"]
            if reasons:
                paused = len(reasons) == 1 and reasons[0].startswith("paused")
                reason = "paused" if paused else "; ".join(reasons)
                store.release_post(post_id, reason)
                if not paused:
                    store.cancel_post(post_id, reason)
                    notifier.send_text(f"Post {post_id} cancelled: {reason}")
                continue
        clip = store.get_clip(clip_id)
        auto = load_auto_campaign(clip["campaign_key"], campaigns_dir)
        request_id, results = post["request_id"], dict(post["results"])
        api_platforms, manual = split_platforms(post["platforms"], config.upload_post.manual_platforms)
        for platform in manual:
            results[platform] = {"url": MANUAL_URL, "success": True, "message": "post by hand"}
        if not api_platforms:
            request_id = request_id or f"manual-{post_id}"
        elif not recovering:
            try:
                upload = client.upload(
                    video_path=clip["path"],
                    platforms=api_platforms,
                    title=clip["title"],
                    caption=clip["caption"],
                    hashtags=clip["hashtags"],
                    campaign=auto,
                    idempotency_key=f"clip-{clip_id}-post-{post_id}",
                )
                request_id = upload.request_id
                _merge(results, upload.immediate_results, api_platforms)
            except UploadPostError as exc:
                request_id = exc.request_id
                if not request_id:
                    attempts = store.get_post(post_id)["attempts"]
                    if exc.retryable and attempts < 3:
                        store.release_post(post_id, str(exc), retry_at=now + timedelta(minutes=15))
                    else:
                        store.fail_post(post_id, str(exc))
                        notifier.send_text(f"Post {post_id} failed: {exc}")
                    continue
            _save_request(store, post_id, request_id, results)
        if api_platforms:
            _poll(client, request_id, results, api_platforms, sleep)
        for platform in api_platforms:
            results.setdefault(platform, {"url": "", "success": None, "message": "URL pending"})
        store.finish_post(
            post_id,
            request_id=request_id,
            results=results,
            posted_at=now,
            submit_deadline=now + timedelta(minutes=auto.campaign.submit_deadline_min),
        )
        _announce(notifier, store.get_post(post_id), auto)
        if manual:
            _send_hand_post(notifier, clip, manual, auto)
        finished.append(post_id)
    return finished
