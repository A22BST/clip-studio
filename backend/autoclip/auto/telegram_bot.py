"""Authenticated async Telegram controls for the automation store."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import suppress
from functools import partial

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import secrets
from .approval import (
    Rerender,
    apply_hook_edit,
    approve,
    begin_edit_hook,
    reject,
    send_pending_previews,
    status_text,
)
from .config import AutoConfig, load_config
from .notify import TelegramNotifier
from .store import Store, StoreError


def build_application(
    store: Store,
    config: AutoConfig,
    token: str | None = None,
    chat_id: int | str | None = None,
    rerender: Rerender | None = None,
    extra_jobs: list[Callable[[Store], object]] | None = None,
) -> Application:
    expected_chat = int(
        chat_id if chat_id is not None else secrets.require_secret(secrets.TELEGRAM_CHAT_ID)
    )
    application = (
        Application.builder()
        .token(token or secrets.require_secret(secrets.TELEGRAM_BOT_TOKEN))
        .build()
    )
    application.bot_data["pending_hooks"] = {}
    notifier = TelegramNotifier()
    # Serialize manual previews, scheduled previews and edits inside this application.
    work_lock = asyncio.Lock()

    def authorized(update: Update) -> bool:
        if update.effective_chat is None or update.effective_chat.id != expected_chat:
            store.log_event("unauthorized_update")
            return False
        return True

    async def run_sync(function, *args):
        async with work_lock:
            return await asyncio.get_running_loop().run_in_executor(None, partial(function, *args))

    async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not authorized(update):
            return
        name = update.effective_message.text.split()[0].split("@")[0].lower()
        if name == "/pause":
            store.set_paused(True, "telegram")
            text = "Paused."
        elif name == "/resume":
            store.set_paused(False, "telegram")
            text = "Resumed."
        elif name == "/status":
            text = status_text(store, config)
        elif name == "/previews":
            count = await run_sync(send_pending_previews, store, notifier, config)
            text = f"Sent {count} previews."
        else:
            text = "Commands: /help /pause /resume /status /previews"
        await update.effective_message.reply_text(text)

    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not authorized(update):
            return
        query = update.callback_query
        try:
            action, raw_id = query.data.split(":", 1)
            item_id = int(raw_id)
        except (AttributeError, ValueError):
            await query.answer("Invalid action.")
            return
        # Acknowledge before hashing/rerendering or other potentially slow work.
        if action == "s":
            store.mark_submitted(item_id)
            await query.answer("Logged")
            return
        await query.answer()
        if action == "a":
            text = await run_sync(approve, store, item_id, expected_chat, config)
        elif action == "r":
            text = await run_sync(reject, store, item_id, expected_chat)
        elif action == "e":
            if rerender is None:
                text = "Hook editing is not configured."
            else:
                pending = context.application.bot_data["pending_hooks"]
                old = pending.pop(expected_chat, None)
                if old:
                    _restore_edit(old[0])
                text = begin_edit_hook(store, item_id)
                clip = store.get_clip(item_id)
                if clip and clip["status"] == "editing":
                    pending[expected_chat] = (item_id, time.monotonic() + 600)
        else:
            return
        if action in ("a", "r"):
            await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(text)

    def _restore_edit(clip_id: int) -> None:
        with suppress(StoreError):
            store.set_clip_status(clip_id, "pending_approval")

    async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not authorized(update):
            return
        pending = context.application.bot_data["pending_hooks"]
        entry = pending.get(expected_chat)
        if entry is None:
            return
        clip_id, expires = entry
        if time.monotonic() >= expires:
            pending.pop(expected_chat, None)
            _restore_edit(clip_id)
            await update.effective_message.reply_text("Hook edit expired. Tap Edit hook again.")
            return
        text = await run_sync(
            apply_hook_edit, store, clip_id, update.effective_message.text, rerender
        )
        clip = store.get_clip(clip_id)
        if clip is None or clip["status"] != "editing":
            pending.pop(expected_chat, None)
        await update.effective_message.reply_text(text)

    async def tick(context: ContextTypes.DEFAULT_TYPE) -> None:
        pending = context.application.bot_data["pending_hooks"]
        for key, (clip_id, expires) in list(pending.items()):
            if time.monotonic() >= expires:
                pending.pop(key, None)
                _restore_edit(clip_id)
        await run_sync(send_pending_previews, store, notifier, config)
        for job in extra_jobs or []:
            try:
                await run_sync(job, store)
            except Exception as exc:
                store.log_event("telegram_job_failed", type(exc).__name__)

    for name in ("start", "help", "pause", "resume", "status", "previews"):
        application.add_handler(CommandHandler(name, command))
    application.add_handler(CallbackQueryHandler(callback, pattern=r"^[ares]:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    if application.job_queue is None:
        raise RuntimeError("Install python-telegram-bot[job-queue] to run automation jobs")
    application.job_queue.run_repeating(tick, interval=60, first=60)
    return application


def run_bot(
    store: Store | None = None,
    config: AutoConfig | None = None,
    token: str | None = None,
    chat_id: int | str | None = None,
    rerender: Rerender | None = None,
    extra_jobs: list[Callable[[Store], object]] | None = None,
) -> None:
    owner = chat_id if chat_id is not None else secrets.get_secret(secrets.TELEGRAM_CHAT_ID)
    if owner is None or str(owner).startswith("-"):
        raise RuntimeError(
            "TELEGRAM_CHAT_ID must be a private chat id (a group would let any member approve)"
        )
    application = build_application(
        store or Store(),
        config or load_config(),
        token or secrets.require_secret(secrets.TELEGRAM_BOT_TOKEN),
        chat_id,
        rerender,
        extra_jobs,
    )
    application.run_polling(
        drop_pending_updates=False, allowed_updates=["message", "callback_query"]
    )
