"""SQLite state for the automation layer: pause flag, jobs, clips, posts, metrics, audit log.

One file, ``<root>/auto/auto.db``. Every operation opens its own short connection (WAL), so the
tick, the Telegram bot and the CLI can use it at the same time. State changes that matter for
safety are enforced HERE as well as in ``gate.py`` (defence in depth):

* a clip is approved only from ``pending_approval`` and only if its file hash equals the hash
  that was previewed to the human (``previewed_sha256``);
* a post can be queued only for an ``approved`` clip;
* ``claim_post`` is an atomic queued -> posting switch, so two processes never both upload.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import auto_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_key TEXT NOT NULL, platform TEXT NOT NULL DEFAULT 'twitch',
  vod_id TEXT NOT NULL, streamer TEXT DEFAULT '', title TEXT DEFAULT '',
  vod_created_at TEXT, url TEXT DEFAULT '',
  start_s REAL NOT NULL DEFAULT 0, end_s REAL NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'queued',
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT DEFAULT '',
  autoclip_job_id TEXT DEFAULT '', export_dir TEXT DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(platform, vod_id, start_s, end_s)
);
CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES jobs(id),
  campaign_key TEXT NOT NULL,
  title TEXT NOT NULL, hook TEXT DEFAULT '', caption TEXT DEFAULT '',
  hashtags TEXT DEFAULT '[]', mentions TEXT DEFAULT '[]',
  qa_score INTEGER NOT NULL DEFAULT 0, spoiler_level TEXT DEFAULT 'none',
  layout TEXT DEFAULT '', path TEXT NOT NULL, duration_s REAL DEFAULT 0,
  report_status TEXT NOT NULL DEFAULT 'exported',
  highlight TEXT DEFAULT '', stream_date TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending_approval',
  previewed_sha256 TEXT DEFAULT '', preview_message_id INTEGER, previewed_at TEXT,
  approved_by TEXT DEFAULT '', approved_sha256 TEXT DEFAULT '', approved_at TEXT,
  rejected_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clip_id INTEGER NOT NULL REFERENCES clips(id),
  scheduled_for TEXT NOT NULL, platforms TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  request_id TEXT DEFAULT '', results TEXT DEFAULT '{}',
  posted_at TEXT, submit_deadline TEXT, submitted_at TEXT,
  reminders_sent INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0, error TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id INTEGER NOT NULL REFERENCES posts(id), platform TEXT NOT NULL,
  fetched_at TEXT NOT NULL, views INTEGER DEFAULT 0, likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0, shares INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT
);
"""

CLIP_STATUSES = (
    "pending_approval", "approved", "rejected", "expired", "low_qa",
    "editing", "posted", "post_failed",
)  # fmt: skip
POST_STATUSES = ("queued", "posting", "posted", "failed", "cancelled")

#: Allowed clip status moves. Anything else raises StoreError.
CLIP_TRANSITIONS: dict[str, set[str]] = {
    "pending_approval": {"approved", "rejected", "expired", "editing"},
    "editing": {"pending_approval", "rejected", "expired"},
    "approved": {"posted", "post_failed", "expired", "rejected"},
    "post_failed": {"approved", "rejected", "expired"},
    "rejected": set(), "expired": set(), "low_qa": set(), "posted": set(),
}  # fmt: skip

APPROVER_PREFIXES = ("discord:", "telegram:", "auto:level2")
JSON_FIELDS = {"hashtags", "mentions", "highlight", "platforms", "results"}


class StoreError(RuntimeError):
    """An illegal state change was refused."""


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for key in JSON_FIELDS & out.keys():
        raw = out[key]
        if isinstance(raw, str):
            try:
                out[key] = json.loads(raw) if raw else ([] if key != "results" else {})
            except json.JSONDecodeError:
                out[key] = raw
    return out


def _enc(key: str, value: Any) -> Any:
    return json.dumps(value, ensure_ascii=False) if key in JSON_FIELDS else value


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else auto_dir() / "auto.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    # -- meta / pause / audit ---------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        with self._conn() as con:
            row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as con:
            con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))

    @property
    def pause_file(self) -> Path:
        """A PAUSE file next to the database: the kill switch that needs no chat app."""
        name = "PAUSE" if self.path.name == "auto.db" else f"{self.path.stem}.PAUSE"
        return self.path.parent / name

    def is_paused(self) -> bool:
        return self.get_meta("paused", "0") == "1" or self.pause_file.exists()

    def set_paused(self, paused: bool, by: str = "") -> None:
        self.set_meta("paused", "1" if paused else "0")
        if paused:
            self.pause_file.write_text(f"paused by {by} at {now_iso()}", encoding="utf-8")
        else:
            self.pause_file.unlink(missing_ok=True)
        self.log_event("pause" if paused else "resume", by)

    # -- per-platform throttle state ---------------------------------------------------
    def platform_pause_until(self, platform: str) -> datetime | None:
        return parse_iso(self.get_meta(f"platform_pause:{platform}") or None)

    def set_platform_pause(self, platform: str, until: datetime | None) -> None:
        self.set_meta(f"platform_pause:{platform}", now_iso(until) if until else "")

    def cap_factor(self, platform: str) -> float:
        try:
            return float(self.get_meta(f"cap_factor:{platform}", "1") or 1)
        except ValueError:
            return 1.0

    def set_cap_factor(self, platform: str, factor: float) -> None:
        self.set_meta(f"cap_factor:{platform}", str(factor))

    def log_event(self, kind: str, detail: str = "") -> None:
        with self._conn() as con:
            con.execute(
                "INSERT INTO events(ts,kind,detail) VALUES(?,?,?)", (now_iso(), kind, detail[:2000])
            )

    def events(self, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM events", ()
        if kind:
            sql, args = sql + " WHERE kind=?", (kind,)
        with self._conn() as con:
            rows = con.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [dict(r) for r in rows]

    # -- jobs -----------------------------------------------------------------------
    def add_job(self, **fields: Any) -> int | None:
        """Insert a queued job; None when the same VOD slice already exists."""
        ts = now_iso()
        fields.setdefault("start_s", 0.0)
        fields.setdefault("end_s", 0.0)
        cols = {**fields, "created_at": ts, "updated_at": ts}
        keys = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        with self._conn() as con:
            try:
                cur = con.execute(f"INSERT INTO jobs({keys}) VALUES({marks})", tuple(cols.values()))
            except sqlite3.IntegrityError:
                return None
            return int(cur.lastrowid)

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self._conn() as con:
            return _row(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list_jobs(self, state: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM jobs", ()
        if state:
            sql, args = sql + " WHERE state=?", (state,)
        with self._conn() as con:
            return [_row(r) for r in con.execute(sql + " ORDER BY id", args).fetchall()]  # type: ignore[misc]

    def vod_known(self, platform: str, vod_id: str) -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM jobs WHERE platform=? AND vod_id=? LIMIT 1", (platform, vod_id)
            ).fetchone()
        return row is not None

    def update_job(self, job_id: int, **fields: Any) -> None:
        fields["updated_at"] = now_iso()
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as con:
            con.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))

    def claim_next_job(self) -> dict[str, Any] | None:
        """Atomically take the oldest queued job (state -> running)."""
        with self._conn() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            con.execute(
                "UPDATE jobs SET state='running', attempts=attempts+1, updated_at=? WHERE id=?",
                (now_iso(), row["id"]),
            )
            return _row(con.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    # -- clips ----------------------------------------------------------------------
    def add_clip(self, **fields: Any) -> int:
        ts = now_iso()
        cols = {k: _enc(k, v) for k, v in fields.items()}
        cols |= {"created_at": ts, "updated_at": ts}
        keys = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        with self._conn() as con:
            cur = con.execute(f"INSERT INTO clips({keys}) VALUES({marks})", tuple(cols.values()))
            return int(cur.lastrowid)

    def get_clip(self, clip_id: int) -> dict[str, Any] | None:
        with self._conn() as con:
            return _row(con.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())

    def list_clips(
        self, status: str | None = None, job_id: int | None = None
    ) -> list[dict[str, Any]]:
        where, args = [], []
        if status:
            where.append("status=?")
            args.append(status)
        if job_id is not None:
            where.append("job_id=?")
            args.append(job_id)
        sql = "SELECT * FROM clips" + (" WHERE " + " AND ".join(where) if where else "")
        with self._conn() as con:
            return [_row(r) for r in con.execute(sql + " ORDER BY id", args).fetchall()]  # type: ignore[misc]

    def update_clip(self, clip_id: int, **fields: Any) -> None:
        """Update non-status columns (status goes through set_clip_status)."""
        if {"status", "approved_by", "approved_sha256", "approved_at"} & fields.keys():
            raise StoreError("status/approval columns change only through the dedicated methods")
        fields["updated_at"] = now_iso()
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as con:
            con.execute(
                f"UPDATE clips SET {sets} WHERE id=?",
                (*[_enc(k, v) for k, v in fields.items()], clip_id),
            )

    def set_clip_status(self, clip_id: int, status: str) -> None:
        if status == "approved":
            raise StoreError("use approve_clip()")
        with self._conn() as con:
            row = con.execute("SELECT status FROM clips WHERE id=?", (clip_id,)).fetchone()
            if row is None:
                raise StoreError(f"no clip {clip_id}")
            if status not in CLIP_TRANSITIONS.get(row["status"], set()):
                raise StoreError(f"clip {clip_id}: {row['status']} -> {status} is not allowed")
            extra = ", rejected_at=?" if status == "rejected" else ""
            args = [status, now_iso()] + ([now_iso()] if extra else []) + [clip_id]
            con.execute(f"UPDATE clips SET status=?, updated_at=?{extra} WHERE id=?", args)
            if status in ("rejected", "expired"):
                con.execute(
                    "UPDATE posts SET status='cancelled', error='clip '||? "
                    "WHERE clip_id=? AND status='queued'",
                    (status, clip_id),
                )

    def mark_previewed(self, clip_id: int, sha256: str, message_id: int | None = None) -> None:
        """Record exactly which file the human was shown. Approval must match this hash."""
        with self._conn() as con:
            n = con.execute(
                "UPDATE clips SET previewed_sha256=?, preview_message_id=?, previewed_at=?, "
                "updated_at=? WHERE id=? AND status='pending_approval'",
                (sha256, message_id, now_iso(), now_iso(), clip_id),
            ).rowcount
        if n != 1:
            raise StoreError(f"clip {clip_id} is not awaiting approval")

    def approve_clip(self, clip_id: int, approved_by: str, sha256: str) -> None:
        if not approved_by.startswith(APPROVER_PREFIXES):
            raise StoreError("approved_by must be 'discord:<id>', 'telegram:<id>' or 'auto:level2'")
        with self._conn() as con:
            row = con.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
            if row is None:
                raise StoreError(f"no clip {clip_id}")
            if row["status"] != "pending_approval":
                raise StoreError(f"clip {clip_id} is {row['status']}, not pending_approval")
            if not row["previewed_sha256"] or row["previewed_sha256"] != sha256:
                raise StoreError(f"clip {clip_id} changed since it was previewed: not approved")
            con.execute(
                "UPDATE clips SET status='approved', approved_by=?, approved_sha256=?, "
                "approved_at=?, updated_at=? WHERE id=?",
                (approved_by, sha256, now_iso(), now_iso(), clip_id),
            )
        self.log_event("approve", f"clip {clip_id} by {approved_by}")

    # -- posts ----------------------------------------------------------------------
    def enqueue_post(self, clip_id: int, scheduled_for: datetime, platforms: list[str]) -> int:
        clip = self.get_clip(clip_id)
        if clip is None or clip["status"] != "approved":
            raise StoreError(f"clip {clip_id} is not approved: refusing to queue a post")
        with self._conn() as con:
            live = con.execute(
                "SELECT platforms FROM posts WHERE clip_id=? "
                "AND status IN ('queued','posting','posted')",
                (clip_id,),
            ).fetchall()
            taken = {p for row in live for p in json.loads(row["platforms"])}
            if taken & set(platforms):
                raise StoreError(f"clip {clip_id} already has a post on {sorted(taken & set(platforms))}")
            cur = con.execute(
                "INSERT INTO posts(clip_id,scheduled_for,platforms,created_at) VALUES(?,?,?,?)",
                (clip_id, now_iso(scheduled_for), json.dumps(platforms), now_iso()),
            )
            return int(cur.lastrowid)

    def get_post(self, post_id: int) -> dict[str, Any] | None:
        with self._conn() as con:
            return _row(con.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone())

    def list_posts(self, status: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM posts", ()
        if status:
            sql, args = sql + " WHERE status=?", (status,)
        with self._conn() as con:
            return [_row(r) for r in con.execute(sql + " ORDER BY id", args).fetchall()]  # type: ignore[misc]

    def due_posts(self, now: datetime | None = None) -> list[dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM posts WHERE status='queued' AND scheduled_for<=? "
                "ORDER BY scheduled_for",
                (now_iso(now),),
            ).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]

    def claim_post(self, post_id: int) -> bool:
        """Atomic queued -> posting. False when another process got it or it was cancelled."""
        with self._conn() as con:
            n = con.execute(
                "UPDATE posts SET status='posting', attempts=attempts+1 "
                "WHERE id=? AND status='queued'",
                (post_id,),
            ).rowcount
        return n == 1

    def release_post(self, post_id: int, error: str = "", retry_at: datetime | None = None) -> None:
        """posting -> queued again (gate denied for now, or a retryable error)."""
        with self._conn() as con:
            con.execute(
                "UPDATE posts SET status='queued', error=?, scheduled_for=COALESCE(?, scheduled_for)"
                " WHERE id=? AND status='posting'",
                (error[:500], now_iso(retry_at) if retry_at else None, post_id),
            )

    def finish_post(
        self,
        post_id: int,
        *,
        request_id: str,
        results: dict[str, Any],
        posted_at: datetime,
        submit_deadline: datetime | None,
    ) -> None:
        with self._conn() as con:
            con.execute(
                "UPDATE posts SET status='posted', request_id=?, results=?, posted_at=?, "
                "submit_deadline=?, error='' WHERE id=?",
                (
                    request_id,
                    json.dumps(results),
                    now_iso(posted_at),
                    now_iso(submit_deadline) if submit_deadline else None,
                    post_id,
                ),
            )
            clip_id = con.execute("SELECT clip_id FROM posts WHERE id=?", (post_id,)).fetchone()[0]
            con.execute(
                "UPDATE clips SET status='posted', updated_at=? WHERE id=?", (now_iso(), clip_id)
            )
        self.log_event("posted", f"post {post_id} clip {clip_id} request {request_id}")

    def fail_post(self, post_id: int, error: str) -> None:
        with self._conn() as con:
            con.execute(
                "UPDATE posts SET status='failed', error=? WHERE id=?", (error[:500], post_id)
            )
        self.log_event("post_failed", f"post {post_id}: {error[:300]}")

    def cancel_post(self, post_id: int, reason: str = "") -> bool:
        with self._conn() as con:
            n = con.execute(
                "UPDATE posts SET status='cancelled', error=? WHERE id=? AND status='queued'",
                (reason[:500], post_id),
            ).rowcount
        return n == 1

    def mark_submitted(self, post_id: int) -> None:
        with self._conn() as con:
            con.execute(
                "UPDATE posts SET submitted_at=? WHERE id=? AND submitted_at IS NULL",
                (now_iso(), post_id),
            )
        self.log_event("submitted", f"post {post_id}")

    def mark_submitted_url(self, url: str) -> int | None:
        """Mark the post that owns this URL as submitted. Returns its id (None if unknown)."""
        wanted = url.strip()
        for post in self.list_posts("posted"):
            if any(r.get("url") == wanted for r in post["results"].values()):
                self.mark_submitted(post["id"])
                return post["id"]
        return None

    def bump_reminders(self, post_id: int) -> None:
        with self._conn() as con:
            con.execute("UPDATE posts SET reminders_sent=reminders_sent+1 WHERE id=?", (post_id,))

    def posts_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Posts that are queued/posting/posted with a schedule inside [start, end)."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM posts WHERE status IN ('queued','posting','posted') "
                "AND scheduled_for>=? AND scheduled_for<? ORDER BY scheduled_for",
                (now_iso(start), now_iso(end)),
            ).fetchall()
        return [_row(r) for r in rows]  # type: ignore[misc]

    # -- metrics ---------------------------------------------------------------------
    def add_metric(
        self, post_id: int, platform: str, *, views: int, likes: int = 0, comments: int = 0,
        shares: int = 0, fetched_at: datetime | None = None,
    ) -> None:  # fmt: skip
        with self._conn() as con:
            con.execute(
                "INSERT INTO metrics(post_id,platform,fetched_at,views,likes,comments,shares) "
                "VALUES(?,?,?,?,?,?,?)",
                (post_id, platform, now_iso(fetched_at), views, likes, comments, shares),
            )

    def latest_metrics(self, post_id: int) -> dict[str, dict[str, Any]]:
        """platform -> newest metric row."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT m.* FROM metrics m JOIN (SELECT platform, MAX(id) mid FROM metrics "
                "WHERE post_id=? GROUP BY platform) x ON m.id=x.mid",
                (post_id,),
            ).fetchall()
        return {r["platform"]: dict(r) for r in rows}
