"""Human approval and preview logic, independent of the Telegram application."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import AutoConfig, auto_dir
from .gate import sha256_file
from .notify import Button, Notifier
from .preview import make_preview
from .store import Store, StoreError, parse_iso

PREVIEW_LIMIT = 45 * 1024 * 1024
#: Approve buttons carry the first characters of the previewed file's hash (``a:<id>:<token>``),
#: so the button on an OLD preview can never approve a newer version of the clip.
TOKEN_LEN = 12
#: A clip left in ``editing`` (modal dismissed, bot restarted) goes back to review after this long.
EDIT_TIMEOUT_MIN = 10


def approved_dir() -> Path:
    path = auto_dir() / "approved"
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_approved_copy(source: Path) -> tuple[Path, str]:
    """Copy a clip to the immutable ``approved/<sha256>.mp4`` and return (copy, sha256).

    The hash is computed from the COPY while it is written, so it describes exactly the bytes that
    will be uploaded; the copy is read-only and its name is its hash (never rewritten)."""
    directory = approved_dir()
    tmp = directory / f".{uuid.uuid4().hex}.tmp"
    digest = hashlib.sha256()
    with open(source, "rb") as src, open(tmp, "wb") as dst:
        for chunk in iter(lambda: src.read(1 << 20), b""):
            digest.update(chunk)
            dst.write(chunk)
    sha = digest.hexdigest()
    final = directory / f"{sha}.mp4"
    if final.exists():
        tmp.unlink(missing_ok=True)
    else:
        os.replace(tmp, final)
        try:
            final.chmod(0o444)
        except OSError:
            pass
    return final, sha


def approve_with_copy(store: Store, clip: dict[str, Any], approved_by: str) -> None:
    """Approve ``clip``: freeze its bytes as ``approved/<sha>.mp4`` and approve THAT file.

    Raises StoreError when the frozen bytes are not the previewed ones (file changed since the
    preview) and OSError when the file is unreadable."""
    copy, sha = make_approved_copy(Path(clip["path"]))
    store.approve_clip(clip["id"], approved_by, sha, path=str(copy))


def preview_token(clip: dict[str, Any]) -> str:
    return (clip.get("previewed_sha256") or "")[:TOKEN_LEN]
Rerender = Callable[[dict[str, Any], str], Path | None]


def _preview(clip: dict[str, Any], sha: str, notifier: Notifier | None = None) -> Path:
    """The file to show: the original when it fits the chat's upload limit, else a small copy."""
    return make_preview(
        Path(clip["path"]),
        sha,
        profile=getattr(notifier, "preview_profile", "telegram"),
        limit_bytes=getattr(notifier, "max_upload_bytes", PREVIEW_LIMIT),
    )


def send_pending_previews(
    store: Store, notifier: Notifier, config: AutoConfig, now: datetime | None = None
) -> int:
    """Send each unpreviewed pending clip; persist the ORIGINAL file's hash."""
    sent = 0
    for clip in store.list_clips("pending_approval"):
        if clip["previewed_at"]:
            continue
        clip_id = clip["id"]
        floor = config.min_qa_to_send
        if config.level2_active:  # nobody approves by hand: below min_qa nothing is ever posted
            floor = max(floor, config.auto_approve.min_qa)
        if clip["qa_score"] < floor:
            store.log_event("low_qa_skipped", f"clip {clip_id}")
            store.set_clip_status(clip_id, "rejected")
            continue
        if not Path(clip["path"]).is_file():
            store.log_event("preview_missing_file", f"clip {clip_id}")
            continue
        try:
            sha = sha256_file(Path(clip["path"]))
            preview = _preview(clip, sha, notifier)
            caption = "\n".join(
                [
                    clip["title"],
                    f"Hook: {clip['hook']}",
                    clip["caption"],
                    " ".join(clip["hashtags"]),
                    f"QA: {clip['qa_score']}",
                    f"Layout: {clip['layout']}",
                    f"Spoiler: {clip['spoiler_level']}",
                    f"Campaign: {clip['campaign_key']}",
                ]
            )
            token = sha[:TOKEN_LEN]
            if config.level2_active:
                caption = (
                    f"AUTO-APPROVED (QA {clip['qa_score']}): posts after the "
                    f"{config.auto_approve.delay_minutes} min review window. "
                    "Tap Reject or send /pause to stop it.\n" + caption
                )
                buttons = [[Button("Reject", f"r:{clip_id}")]]
            else:
                buttons = [
                    [Button("Approve", f"a:{clip_id}:{token}"), Button("Reject", f"r:{clip_id}")],
                    [Button("Edit hook", f"e:{clip_id}")],
                ]
            message_id = notifier.send_video(preview, caption, buttons)
            store.mark_previewed(clip_id, sha, message_id)
            sent += 1
        except Exception as exc:
            store.log_event("preview_failed", f"clip {clip_id}: {type(exc).__name__}")
    return sent


def approve(
    store: Store,
    clip_id: int,
    chat_id: int,
    config: AutoConfig,
    source: str = "telegram",
    token: str | None = None,
) -> str:
    clip = store.get_clip(clip_id)
    if clip is None:
        return "Clip not found."
    if token and token != preview_token(clip):
        return "This preview is out of date (the hook was edited). Use the newest preview."
    try:
        approve_with_copy(store, clip, f"{source}:{chat_id}")
    except OSError:
        return "Cannot approve: the clip file is unavailable."
    except StoreError:
        return "Cannot approve: the file changed or the clip is no longer awaiting approval."
    return "Approved."


def reject(store: Store, clip_id: int, chat_id: int, source: str = "telegram") -> str:
    try:
        store.set_clip_status(clip_id, "rejected")
    except StoreError:
        return "Cannot reject: the clip is no longer awaiting review."
    store.log_event("reject", f"clip {clip_id} by {source}:{chat_id}")
    return "Rejected."


def begin_edit_hook(store: Store, clip_id: int) -> str:
    try:
        store.set_clip_status(clip_id, "editing")
    except StoreError:
        return "Cannot edit: the clip is no longer awaiting approval."
    return "Send a new hook (1-60 characters, one line)."


def apply_hook_edit(store: Store, clip_id: int, new_hook: str, rerender: Rerender) -> str:
    clip = store.get_clip(clip_id)
    if clip is None or clip["status"] != "editing":
        return "Cannot edit: the clip is not being edited."
    if (
        not 1 <= len(new_hook) <= 60
        or not new_hook.strip()
        or any(char in new_hook for char in "\r\n")
    ):
        return "Hook must be 1-60 characters on one line."
    try:
        path = rerender(clip, new_hook)
        if path is None or not Path(path).is_file():
            raise ValueError("Rerender did not produce a file")
        store.update_clip(
            clip_id,
            path=str(path),
            hook=new_hook,
            previewed_at=None,
            previewed_sha256="",
            preview_message_id=None,
        )
    except Exception as exc:
        store.set_clip_status(clip_id, "pending_approval")
        store.log_event("hook_edit_failed", f"clip {clip_id}: {type(exc).__name__}")
        return "Hook edit failed. The previous version is still awaiting approval."
    store.set_clip_status(clip_id, "pending_approval")
    return "Hook updated. A fresh preview will be sent for approval."


def restore_stale_edits(
    store: Store, now: datetime | None = None, max_minutes: int = EDIT_TIMEOUT_MIN
) -> int:
    """Put clips stuck in ``editing`` back to ``pending_approval`` (their last preview stays valid)."""
    now = now or datetime.now(UTC)
    restored = 0
    for clip in store.list_clips("editing"):
        touched = parse_iso(clip["updated_at"]) or now
        if now - touched >= timedelta(minutes=max_minutes):
            try:
                store.set_clip_status(clip["id"], "pending_approval")
            except StoreError:
                continue
            store.log_event("edit_timeout", f"clip {clip['id']}")
            restored += 1
    return restored


def submitted_text(store: Store, argument: str = "") -> str:
    """``/submitted [url]``: log a Content Rewards submission. Without a URL it logs the only post
    that is still waiting; with several waiting it lists their URLs."""
    argument = argument.strip()
    if argument:
        post_id = store.mark_submitted_url(argument)
        if post_id:
            return f"Logged post {post_id} as submitted."
        return "No posted clip has that URL. Send /submitted <post URL>."
    waiting = store.awaiting_submission()
    if not waiting:
        return "Nothing is waiting for submission."
    if len(waiting) == 1:
        store.mark_submitted(waiting[0]["id"])
        return f"Logged post {waiting[0]['id']} as submitted."
    lines = ["Several posts are waiting. Send /submitted <post URL> for one of:"]
    for post in waiting:
        urls = [r.get("url") for r in post["results"].values() if r.get("url")]
        lines.append(f"post {post['id']}: " + (" ".join(urls) or "URL pending"))
    return "\n".join(lines)


def status_text(store: Store, config: AutoConfig) -> str:
    tz = ZoneInfo(config.post.timezone)
    today = datetime.now(tz).date()
    counts = Counter(clip["status"] for clip in store.list_clips())
    posts = store.list_posts()
    queued = [p for p in posts if p["status"] == "queued"]

    def is_today(value: str | None) -> bool:
        parsed = parse_iso(value)
        return parsed is not None and parsed.astimezone(tz).date() == today

    next_time = min((p["scheduled_for"] for p in queued), default=None)
    next_local = parse_iso(next_time)
    lines = [
        "Automation: " + ("paused" if store.is_paused() else "running"),
        "Mode: " + config.mode_text(),
        "Clips: " + (", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none"),
        f"Queued today: {sum(is_today(p['scheduled_for']) for p in queued)}",
        "Posted today: "
        + str(sum(p["status"] == "posted" and is_today(p["posted_at"]) for p in posts)),
        "Next queued: "
        + (next_local.astimezone(tz).strftime("%Y-%m-%d %H:%M") if next_local else "none"),
        "Last events:",
    ]
    # Only event kinds/timestamps: arbitrary event details may contain sensitive information.
    lines += [f"{e['ts']} {e['kind']}" for e in store.events(limit=3)]
    return "\n".join(lines)


def auto_approve_pending(store: Store, config: AutoConfig, now: datetime | None = None) -> int:
    """Level 2 only (``level: 2`` AND ``auto_approve.enabled: true``): approve previewed clips whose
    QA is at or above ``auto_approve.min_qa``. With level 2 off this does nothing at all. The gate
    still re-checks everything (rules, hash, caps) at post time and honours the review delay."""
    if not config.level2_active:
        return 0
    approved = 0
    for clip in store.list_clips("pending_approval"):
        if not clip["previewed_sha256"] or clip["qa_score"] < config.auto_approve.min_qa:
            continue
        try:
            approve_with_copy(store, clip, "auto:level2")
            approved += 1
        except (OSError, StoreError):
            continue  # unreadable or changed since the preview: stays pending, never approved
    return approved
