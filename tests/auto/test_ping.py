"""The one-way Telegram ping: post announcements, /submitted, composite notifier."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from autoclip.auto import cli, poster
from autoclip.auto.notify import Button, CompositeNotifier, RecordingNotifier

KW = {"probe_duration": lambda _p: 30.0}


class Client:
    def __init__(self):
        self.uploads = []

    def upload(self, **kw):
        from autoclip.auto.uploadpost import UploadResult

        self.uploads.append(kw)
        return UploadResult("r1", [])

    def status(self, request_id):
        return {"status": "completed", "results": [
            {"platform": "youtube", "success": True, "post_url": "https://yt.test/abc"}]}  # fmt: skip

    def history(self, request_id):
        return []


def test_posted_message_has_platform_campaign_deadline_and_copyable_url(env, make_clip):
    clip = make_clip(approve=True)
    now = datetime.now(UTC)
    env.store.enqueue_post(clip, now - timedelta(minutes=1), ["youtube"])
    n = RecordingNotifier()
    poster.post_due(env.store, env.config, n, Client(), now=now, gate_kwargs=KW, sleep=lambda s: None)
    text = next(t for t, _ in n.texts if "Posted on youtube" in t)
    assert "submit to Content Rewards now (30 min)" in text
    assert "Campaign: Test Campaign" in text and "Deadline: " in text
    assert text.splitlines()[-1] == "https://yt.test/abc"  # the URL alone on the last line


def test_composite_pings_text_without_buttons_but_never_videos(tmp_path):
    primary, ping = RecordingNotifier(), RecordingNotifier()
    n = CompositeNotifier(primary, ping)
    n.send_text("hello", [[Button("Submitted", "s:1")]])
    n.send_video(tmp_path / "x.mp4", "cap", [[Button("Approve", "a:1")]])
    assert primary.texts[0][1] and ping.texts == [("hello", None)]
    assert len(primary.videos) == 1 and ping.videos == []


def test_a_broken_ping_never_breaks_the_primary(tmp_path):
    class Broken:
        def send_text(self, *a, **k):
            raise RuntimeError("telegram down")

    primary = RecordingNotifier()
    CompositeNotifier(primary, Broken()).send_text("still delivered")
    assert primary.texts[0][0] == "still delivered"


def test_submitted_by_url_marks_the_post(env, make_clip):
    clip = make_clip(approve=True)
    now = datetime.now(UTC)
    pid = env.store.enqueue_post(clip, now - timedelta(minutes=1), ["youtube"])
    poster.post_due(env.store, env.config, RecordingNotifier(), Client(), now=now, gate_kwargs=KW,
                    sleep=lambda s: None)  # fmt: skip
    assert env.store.mark_submitted_url("https://nope.test") is None
    assert env.store.mark_submitted_url(" https://yt.test/abc ") == pid
    assert env.store.get_post(pid)["submitted_at"]


def test_ping_is_on_whenever_telegram_secrets_are_set(env, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "d")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "1")
    notifier = cli._notifier(env.config)
    assert isinstance(notifier, CompositeNotifier)  # TELEGRAM_* come from the fixture
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    monkeypatch.setattr("autoclip.auto.secrets.get_secret", lambda n: None if "TELEGRAM" in n else "x")
    assert not isinstance(cli._notifier(env.config), CompositeNotifier)
