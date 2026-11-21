"""Exercise PTB handler callbacks directly, without polling or network access."""

import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from autoclip.auto import telegram_bot
from autoclip.auto.config import AutoConfig
from autoclip.auto.gate import sha256_file
from autoclip.auto.notify import RecordingNotifier
from autoclip.auto.store import Store
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler
from telegram.request import BaseRequest


class OfflineRequest(BaseRequest):
    """Prevent accidental Telegram requests, including from newly added test cases."""

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, *args, **kwargs):
        raise AssertionError("Network requests are forbidden in these tests")


@pytest.fixture
def setup_bot(tmp_path, monkeypatch):
    # PTB's optional APScheduler dependency is not required for offline handler tests.
    queue = Mock()
    monkeypatch.setattr("telegram.ext._applicationbuilder.JobQueue", lambda: queue)
    monkeypatch.setattr(
        "telegram.ext._applicationbuilder.HTTPXRequest", lambda **kwargs: OfflineRequest()
    )
    monkeypatch.setattr(telegram_bot, "TelegramNotifier", RecordingNotifier)
    monkeypatch.setattr(telegram_bot.secrets, "get_secret", lambda name: "42")
    store = Store(tmp_path / "auto.db")
    job_id = store.add_job(campaign_key="campaign", vod_id="vod")
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake mp4")
    clip_id = store.add_clip(
        job_id=job_id,
        campaign_key="campaign",
        title="Title",
        path=str(path),
        qa_score=90,
    )
    store.mark_previewed(clip_id, sha256_file(path), 100)
    rerender = Mock(return_value=path)
    app = telegram_bot.build_application(store, AutoConfig(), token="123:abc", rerender=rerender)
    return store, clip_id, app, queue, rerender


def update(chat_id=42, text="/status", data=None):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    query = (
        None
        if data is None
        else SimpleNamespace(
            data=data,
            message=message,
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
        )
    )
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=message,
        callback_query=query,
    )


def handler(app, kind, name=None):
    return next(
        h for h in app.handlers[0] if isinstance(h, kind) and (name is None or name in h.commands)
    )


async def dispatch(app, event, kind, name=None):
    await handler(app, kind, name).callback(event, SimpleNamespace(application=app))


@pytest.mark.parametrize(
    "kind,name,data",
    [
        (CommandHandler, "pause", None),
        (CallbackQueryHandler, None, "a:1"),
        (CallbackQueryHandler, None, "s:1"),
        (MessageHandler, None, None),
    ],
)
async def test_unauthorized_is_silent_and_only_logs_counter(setup_bot, kind, name, data):
    store, clip_id, app, _, _ = setup_bot
    before = store.get_clip(clip_id)
    event = update(chat_id=999, text="/pause secret text", data=data)
    await dispatch(app, event, kind, name)
    assert store.get_clip(clip_id) == before
    assert not store.is_paused()
    assert store.list_posts() == []
    event.effective_message.reply_text.assert_not_awaited()
    if event.callback_query:
        event.callback_query.answer.assert_not_awaited()
    assert len(store.events("unauthorized_update")) == 1
    assert store.events("unauthorized_update")[0]["detail"] == ""


async def test_pause_resume_and_status(setup_bot):
    store, _, app, _, _ = setup_bot
    await dispatch(app, update(text="/pause"), CommandHandler, "pause")
    assert store.is_paused()
    assert store.events("pause")[0]["detail"] == "telegram"
    await dispatch(app, update(text="/resume"), CommandHandler, "resume")
    assert not store.is_paused()
    event = update(text="/status")
    await dispatch(app, event, CommandHandler, "status")
    assert "running" in event.effective_message.reply_text.call_args.args[0]


async def test_approve_callback_answers_and_removes_buttons(setup_bot):
    store, clip_id, app, _, _ = setup_bot
    event = update(data=f"a:{clip_id}")
    await dispatch(app, event, CallbackQueryHandler)
    assert store.get_clip(clip_id)["approved_by"] == "telegram:42"
    event.callback_query.answer.assert_awaited_once()
    event.callback_query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
    event.effective_message.reply_text.assert_awaited_once_with("Approved.")
    assert store.list_posts() == []


async def test_approve_callback_with_preview_token(setup_bot):
    store, clip_id, app, _, _ = setup_bot
    stale = update(data=f"a:{clip_id}:000000000000")
    await dispatch(app, stale, CallbackQueryHandler)
    assert "out of date" in stale.callback_query.message.reply_text.call_args.args[0]
    assert store.get_clip(clip_id)["status"] == "pending_approval"
    token = store.get_clip(clip_id)["previewed_sha256"][:12]
    fresh = update(data=f"a:{clip_id}:{token}")
    await dispatch(app, fresh, CallbackQueryHandler)
    assert store.get_clip(clip_id)["status"] == "approved"


async def test_submitted_command_without_url_logs_the_only_waiting_post(setup_bot):
    store, clip_id, app, _, _ = setup_bot
    event = update(text="/submitted")
    await dispatch(app, event, CommandHandler, "submitted")
    assert "Nothing is waiting" in event.effective_message.reply_text.call_args.args[0]


async def test_reject_callback(setup_bot):
    store, clip_id, app, _, _ = setup_bot
    event = update(data=f"r:{clip_id}")
    await dispatch(app, event, CallbackQueryHandler)
    assert store.get_clip(clip_id)["status"] == "rejected"
    event.callback_query.answer.assert_awaited_once()
    event.callback_query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)


async def test_submitted_callback(setup_bot):
    store, clip_id, app, _, _ = setup_bot
    store.approve_clip(clip_id, "telegram:42", store.get_clip(clip_id)["previewed_sha256"])
    post_id = store.enqueue_post(clip_id, datetime.now(UTC), ["youtube"])
    event = update(data=f"s:{post_id}")
    await dispatch(app, event, CallbackQueryHandler)
    assert store.get_post(post_id)["submitted_at"]
    event.callback_query.answer.assert_awaited_once_with("Logged")


async def test_text_only_edits_after_tap_and_runs_in_executor(setup_bot):
    store, clip_id, app, _, rerender = setup_bot
    event = update(text="ignored")
    await dispatch(app, event, MessageHandler)
    event.effective_message.reply_text.assert_not_awaited()
    await dispatch(app, update(data=f"e:{clip_id}"), CallbackQueryHandler)
    assert store.get_clip(clip_id)["status"] == "editing"
    assert 42 in app.bot_data["pending_hooks"]
    main_thread = threading.get_ident()
    worker_threads = []
    path = store.get_clip(clip_id)["path"]
    rerender.side_effect = lambda clip, hook: worker_threads.append(threading.get_ident()) or path
    await dispatch(app, update(text="New hook"), MessageHandler)
    assert worker_threads[0] != main_thread
    assert store.get_clip(clip_id)["hook"] == "New hook"
    assert store.get_clip(clip_id)["previewed_at"] is None
    assert app.bot_data["pending_hooks"] == {}


async def test_hook_expiry_restores_pending(setup_bot):
    store, clip_id, app, _, rerender = setup_bot
    await dispatch(app, update(data=f"e:{clip_id}"), CallbackQueryHandler)
    app.bot_data["pending_hooks"][42] = (clip_id, time.monotonic() - 1)
    event = update(text="Too late")
    await dispatch(app, event, MessageHandler)
    assert store.get_clip(clip_id)["status"] == "pending_approval"
    rerender.assert_not_called()
    assert "expired" in event.effective_message.reply_text.call_args.args[0]


async def test_repeating_job_and_manual_previews(setup_bot, monkeypatch):
    store, _, app, queue, _ = setup_bot
    previews = Mock(return_value=2)
    monkeypatch.setattr(telegram_bot, "send_pending_previews", previews)
    call = queue.run_repeating.call_args
    assert call.kwargs == {"interval": 60, "first": 60}
    await call.args[0](SimpleNamespace(application=app))
    assert previews.call_count == 1
    event = update(text="/previews")
    await dispatch(app, event, CommandHandler, "previews")
    assert previews.call_count == 2
    event.effective_message.reply_text.assert_awaited_once_with("Sent 2 previews.")


async def test_extra_jobs_are_isolated_and_executed(setup_bot, monkeypatch):
    store, _, _, queue, _ = setup_bot
    first, second = Mock(side_effect=RuntimeError("failure")), Mock()
    monkeypatch.setattr(telegram_bot, "send_pending_previews", Mock(return_value=0))
    app = telegram_bot.build_application(
        store,
        AutoConfig(),
        token="123:abc",
        chat_id=42,
        extra_jobs=[first, second],
    )
    await queue.run_repeating.call_args.args[0](SimpleNamespace(application=app))
    first.assert_called_once_with(store)
    second.assert_called_once_with(store)
    assert store.events("telegram_job_failed")[0]["detail"] == "RuntimeError"


def test_missing_job_queue_has_actionable_error(setup_bot, monkeypatch):
    store, _, _, _, _ = setup_bot
    monkeypatch.setattr("telegram.ext._applicationbuilder.JobQueue", lambda: None)
    with pytest.raises(RuntimeError, match=r"python-telegram-bot\[job-queue\]"):
        telegram_bot.build_application(store, AutoConfig(), token="123:abc", chat_id=42)


def test_run_bot_polling_options(monkeypatch):
    app = Mock()
    build = Mock(return_value=app)
    monkeypatch.setattr(telegram_bot, "build_application", build)
    monkeypatch.setattr(telegram_bot.secrets, "require_secret", Mock(return_value="123:abc"))
    telegram_bot.run_bot(store=Mock(), config=AutoConfig(), chat_id=123)
    app.run_polling.assert_called_once_with(
        drop_pending_updates=False, allowed_updates=["message", "callback_query"]
    )
