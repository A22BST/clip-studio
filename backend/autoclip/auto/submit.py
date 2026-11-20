"""Idempotent campaign submission reminders."""

from datetime import UTC, datetime, timedelta
from math import ceil

from .campaign_meta import load_auto_campaign
from .notify import Notifier
from .poster import _buttons
from .store import Store, parse_iso


def send_reminders(store: Store, notifier: Notifier, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    for post in store.list_posts("posted"):
        if post["submitted_at"] or not post["submit_deadline"]:
            continue
        deadline = parse_iso(post["submit_deadline"])
        posted = parse_iso(post["posted_at"])
        sent = post["reminders_sent"]
        clip = store.get_clip(post["clip_id"])
        auto = load_auto_campaign(clip["campaign_key"])
        buttons = _buttons(post["id"], auto)
        if now >= deadline:
            # A missed tick must not suppress the final message or send stale reminders.
            if sent < 3:
                notifier.send_text(f"Deadline passed: {clip['title']}", buttons)
                while sent < 3:
                    store.bump_reminders(post["id"])
                    sent += 1
        else:
            while sent < 2 and now >= posted + timedelta(minutes=10 * (sent + 1)):
                left = ceil((deadline - now).total_seconds() / 60)
                notifier.send_text(f"{left} min left to submit {clip['title']}", buttons)
                store.bump_reminders(post["id"])
                sent += 1
