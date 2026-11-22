"""One scheduler tick: watch -> run queued jobs -> previews -> schedule -> post -> reminders.

Run by Task Scheduler every 30 minutes (``clip-auto tick``) and, for the post half, by the bot
process every minute. Both entry points are safe to run at the same time: the work is claimed
atomically in the store, and posting always goes through ``gate.check_post_allowed``.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import approval, diskguard, outbox, poster, runner, schedule, submit, watcher
from .config import AutoConfig, auto_dir
from .notify import Notifier
from .store import Store

log = logging.getLogger(__name__)


def claim_tick_job(store: Store, backfill_run: int, now: datetime | None = None):
    """Claim recent work first, reserving historical video hours atomically (UTC day)."""
    from .campaign_meta import BackfillConfig, load_auto_campaign
    from .store import now_iso

    day = (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()
    usage_key = f"backfill:hours:{day}"
    with store._conn() as con:
        con.execute("BEGIN IMMEDIATE")
        rows = con.execute(
            "SELECT jobs.*, EXISTS(SELECT 1 FROM meta WHERE key='backfill:job:' || jobs.id) "
            "AS backfill_job FROM jobs WHERE state='queued' "
            "ORDER BY backfill_job, vod_created_at DESC, id"
        ).fetchall()
        for row in rows:
            job = dict(row)
            if job.pop("backfill_job"):
                try:
                    limits = load_auto_campaign(job["campaign_key"]).meta.backfill
                except (FileNotFoundError, ValueError):
                    limits = BackfillConfig()
                if backfill_run >= limits.max_slices_per_tick:
                    continue
                override = con.execute("SELECT value FROM meta WHERE key=?",
                                       (f"backfill:daily_limit:{job['campaign_key']}",)).fetchone()
                daily_limit = float(override[0]) if override else limits.max_hours_per_day
                usage = con.execute("SELECT value FROM meta WHERE key=?", (usage_key,)).fetchone()
                hours = float(usage[0]) if usage else 0
                cost = (job["end_s"] - job["start_s"]) / 3600
                if cost <= 0 or hours + cost > daily_limit + 1e-9:
                    continue
                con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                            (usage_key, str(hours + cost)))
            con.execute("UPDATE jobs SET state='running', attempts=attempts+1, updated_at=? WHERE id=?",
                        (now_iso(), job["id"]))
            job.update(state="running", attempts=job["attempts"] + 1)
            return job
    return None


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
) -> dict[str, Any]:
    """The cheap half: previews for new clips, scheduling of approved ones, due posts, reminders.

    ``dry_run``: everything except the upload; queued posts only produce "WOULD POST" pings."""
    if not poster.publisher_configured(client):
        log.info(poster.OUTBOX_ONLY)
        store.log_event("outbox_only", poster.OUTBOX_ONLY)
        key = "would_post" if dry_run else "posted"
        return {"previews": 0, "scheduled": 0, key: 0, "publisher": poster.OUTBOX_ONLY}
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


def _outbox_entries(config: AutoConfig) -> dict[str, Any]:
    """Snapshot the ledger because after_render deliberately has no return value."""
    try:
        return json.loads((outbox.outbox_dir(config) / "outbox.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
    before = _outbox_entries(config)
    summary.update(outbox_copied=0, outbox_held=0)
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
            backfill_run = 0
            for _ in range(max_jobs):
                if store.is_paused() or not diskguard.disk_ok(config)[0]:
                    break
                job = claim_tick_job(store, backfill_run, now)
                if job is None:
                    break
                if store.get_meta(f"backfill:job:{job['id']}"):
                    backfill_run += 1
                summary["clips"] += process(store, config, job)
                try:
                    outbox.after_render(store, config, job, now=now, dry_run=dry_run)
                except Exception:
                    log.exception("Outbox failed for job %s", job["id"])
                summary["jobs_run"] += 1
    for key, entry in _outbox_entries(config).items():
        if key not in before and entry.get("status") in ("copied", "held"):
            summary[f"outbox_{entry['status']}"] += 1
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
