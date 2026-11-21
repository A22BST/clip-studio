"""Idempotent campaign submission reminders ("submit now" until /submitted or the deadline)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from math import ceil

from .campaign_meta import load_auto_campaign
from .notify import Notifier
from .poster import _buttons
from .store import Store, parse_iso

DEFAULT_REMINDERS = (20,)


def _urls(post: dict) -> str:
    urls = [r.get("url") for r in post["results"].values() if r.get("url")]
    return "\n".join(urls)


def send_reminders(
    store: Store,
    notifier: Notifier,
    now: datetime | None = None,
    reminder_minutes: Sequence[int] = DEFAULT_REMINDERS,
) -> None:
    """One reminder per entry of ``reminder_minutes`` (minutes after the post), then a final
    "deadline passed" message. ``reminders_sent`` counts them, so a missed tick never repeats one."""
    now = now or datetime.now(UTC)
    offsets = sorted(reminder_minutes)
    final = len(offsets) + 1
    for post in store.list_posts("posted"):
        if post["submitted_at"] or not post["submit_deadline"]:
            continue
        deadline = parse_iso(post["submit_deadline"])
        posted = parse_iso(post["posted_at"])
        sent = post["reminders_sent"]
        clip = store.get_clip(post["clip_id"])
        auto = load_auto_campaign(clip["campaign_key"])
        buttons = _buttons(post["id"], auto)
        link = _urls(post)
        if now >= deadline:
            # A missed tick must not suppress the final message or send stale reminders.
            if sent < final:
                text = f"Deadline passed: {clip['title']}"
                notifier.send_text(text + (f"\n{link}" if link else ""), buttons)
                while sent < final:
                    store.bump_reminders(post["id"])
                    sent += 1
        else:
            while sent < len(offsets) and now >= posted + timedelta(minutes=offsets[sent]):
                left = ceil((deadline - now).total_seconds() / 60)
                text = f"{left} min left to submit {clip['title']} (/submitted when done)"
                notifier.send_text(text + (f"\n{link}" if link else ""), buttons)
                store.bump_reminders(post["id"])
                sent += 1
