"""One scheduler tick: watch -> run queued jobs -> previews -> schedule -> post -> reminders.

Run by Task Scheduler every 30 minutes (``clip-auto tick``) and, for the post half, by the bot
process every minute. Both entry points are safe to run at the same time: the work is claimed
atomically in the store, and posting always goes through ``gate.check_post_allowed``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from . import approval, diskguard, poster, runner, submit, watcher
from .config import AutoConfig, auto_dir
from .notify import Notifier
from .store import Store

log = logging.getLogger(__name__)


class TickLock:
    """A pid lock file, so two ticks never run the heavy part at once."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or auto_dir() / "tick.lock"
        self.held = False

    def __enter__(self) -> TickLock:
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip())
                os.kill(pid, 0)  # raises when that process is gone
                return self
            except (ValueError, OSError):
                pass  # stale lock
        self.path.write_text(str(os.getpid()))
        self.held = True
        return self

    def __exit__(self, *exc: object) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)


def post_cycle(
    store: Store,
    config: AutoConfig,
    notifier: Notifier,
    client: Any = None,
    *,
    now: datetime | None = None,
    gate_kwargs: dict[str, Any] | None = None,
) -> dict[str, int]:
    """The cheap half: previews for new clips, scheduling of approved ones, due posts, reminders."""
    previews = approval.send_pending_previews(store, notifier, config, now)
    scheduled = poster.schedule_approved(store, config, now)
    posted = poster.post_due(store, config, notifier, client, now=now, gate_kwargs=gate_kwargs)
    submit.send_reminders(store, notifier, now)
    return {"previews": previews, "scheduled": len(scheduled), "posted": len(posted)}


def tick(
    store: Store,
    config: AutoConfig,
    notifier: Notifier,
    *,
    client: Any = None,
    now: datetime | None = None,
    scan: Callable[..., list[int]] = watcher.scan,
    process: Callable[..., int] = runner.process_job,
    max_jobs: int = 3,
    gate_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"new_jobs": 0, "jobs_run": 0, "clips": 0, "skipped": ""}
    if store.is_paused():
        summary["skipped"] = "paused: no new jobs"
    else:
        ok, why = diskguard.disk_ok(config)
        if not ok:
            summary["skipped"] = why
            store.log_event("disk_guard", why)
        else:
            try:
                summary["new_jobs"] = len(scan(store, config, now=now))
            except Exception as exc:  # a Twitch outage must not stop posting
                store.log_event("watch_error", f"{type(exc).__name__}: {str(exc)[:200]}")
            for _ in range(max_jobs):
                if store.is_paused() or not diskguard.disk_ok(config)[0]:
                    break
                job = store.claim_next_job()
                if job is None:
                    break
                summary["clips"] += process(store, config, job)
                summary["jobs_run"] += 1
    summary.update(post_cycle(store, config, notifier, client, now=now, gate_kwargs=gate_kwargs))
    try:
        runner.cleanup_sources(store, config)
    except OSError as exc:
        log.warning("cleanup failed: %s", exc)
    return summary
