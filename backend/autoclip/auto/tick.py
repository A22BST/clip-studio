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

from . import approval, diskguard, outbox, poster, runner, schedule, submit, watcher
from .config import AutoConfig, auto_dir
from .notify import Notifier
from .store import Store

log = logging.getLogger(__name__)


def _pid_alive(pid: int) -> bool:
    """Is that process running? (``os.kill(pid, 0)`` would TERMINATE it on Windows.)"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class TickLock:
    """A pid lock file, so two ticks never run the heavy part at once."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or auto_dir() / "tick.lock"
        self.held = False

    def __enter__(self) -> TickLock:
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip())
                if _pid_alive(pid):
                    return self
            except ValueError:
                pass  # stale or unreadable lock
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
    dry_run: bool = False,
) -> dict[str, int]:
    """The cheap half: previews for new clips, scheduling of approved ones, due posts, reminders.

    ``dry_run``: everything except the upload; queued posts only produce "WOULD POST" pings."""
    approval.restore_stale_edits(store, now)
    previews = approval.send_pending_previews(store, notifier, config, now)
    approval.auto_approve_pending(store, config, now)
    schedule.expire_stale(store, config, now)
    scheduled = poster.schedule_approved(store, config, now)
    posted = poster.post_due(
        store, config, notifier, client, now=now, gate_kwargs=gate_kwargs, dry_run=dry_run
    )
    submit.send_reminders(store, notifier, now, config.submit.reminder_minutes)
    key = "would_post" if dry_run else "posted"
    return {"previews": previews, "scheduled": len(scheduled), key: len(posted)}


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
    dry_run: bool = False,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"new_jobs": 0, "jobs_run": 0, "clips": 0, "skipped": ""}
    if dry_run:
        summary["dry_run"] = True
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
                try:
                    outbox.after_render(store, config, job, now=now, dry_run=dry_run)
                except Exception:
                    log.exception("Outbox failed for job %s", job["id"])
                summary["jobs_run"] += 1
    summary.update(
        post_cycle(
            store, config, notifier, client, now=now, gate_kwargs=gate_kwargs, dry_run=dry_run
        )
    )
    try:
        runner.cleanup_sources(store, config)
    except OSError as exc:
        log.warning("cleanup failed: %s", exc)
    return summary
