"""Discord backend: REST notifier shape, button logic, owner-only authorisation, preview ladder."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from autoclip.auto import approval, discord_bot, discord_notify, gate, preview
from autoclip.auto.notify import Button, NotifyError
from autoclip.auto.store import StoreError

OWNER, CHANNEL = "555", "777"


@pytest.fixture
def dsc(env, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token-xyz")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", CHANNEL)
    monkeypatch.setenv("DISCORD_OWNER_ID", OWNER)
    return env


def transport(seen, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"id": "123456789012345678"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_send_video_shape(dsc, tmp_path):
    seen: list[httpx.Request] = []
    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")
    n = discord_notify.DiscordNotifier(transport(seen))
    mid = n.send_video(video, "Title line\nrest", [[Button("Approve", "a:1"), Button("Open", url="https://e.t")]])
    req = seen[0]
    assert mid == 123456789012345678
    assert req.url.path == f"/api/v10/channels/{CHANNEL}/messages"
    assert req.headers["authorization"] == "Bot bot-token-xyz"
    body = req.read()
    assert b"payload_json" in body and b'"custom_id": "a:1"' in body and b'"style": 5' in body


def test_send_text_components_and_no_mentions(dsc):
    seen: list[httpx.Request] = []
    discord_notify.DiscordNotifier(transport(seen)).send_text("hi @everyone", [[Button("Submitted", "s:3")]])
    payload = json.loads(seen[0].read())
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["components"][0]["components"][0]["custom_id"] == "s:3"


def test_notifier_errors_never_contain_the_token(dsc):
    n = discord_notify.DiscordNotifier(transport([], status=403))
    with pytest.raises(NotifyError) as err:
        n.send_text("x")
    assert "bot-token-xyz" not in str(err.value)


def test_notifier_cannot_choose_a_channel():
    import inspect

    for name in ("send_text", "send_video"):
        assert "channel" not in str(inspect.signature(getattr(discord_notify.DiscordNotifier, name)))


def test_authorization_is_owner_and_channel_only():
    assert discord_bot.authorized(555, 777, OWNER, CHANNEL)
    assert not discord_bot.authorized(556, 777, OWNER, CHANNEL)  # someone else
    assert not discord_bot.authorized(555, 778, OWNER, CHANNEL)  # wrong channel
    assert not discord_bot.authorized(None, 777, OWNER, CHANNEL)
    assert not discord_bot.authorized(555, None, OWNER, CHANNEL)  # DM


def test_button_approve_records_discord_owner_and_gate_accepts(dsc, make_clip):
    cid = make_clip()
    sha = gate.sha256_file(dsc.store.get_clip(cid)["path"])
    dsc.store.mark_previewed(cid, sha, 1)
    reply, follow = discord_bot.handle_button(dsc.store, dsc.config, f"a:{cid}", OWNER)
    assert reply == "Approved." and follow is None
    assert dsc.store.get_clip(cid)["approved_by"] == f"discord:{OWNER}"
    result = gate.check_post_allowed(
        dsc.store, cid, config=dsc.config, platforms=["tiktok"], probe_duration=lambda _p: 30.0
    )
    assert result.allowed, result.reasons


def test_gate_rejects_approval_from_a_different_discord_user(dsc, make_clip):
    cid = make_clip()
    sha = gate.sha256_file(dsc.store.get_clip(cid)["path"])
    dsc.store.mark_previewed(cid, sha, 1)
    dsc.store.approve_clip(cid, "discord:999", sha)  # not the owner
    result = gate.check_post_allowed(
        dsc.store, cid, config=dsc.config, platforms=["tiktok"], probe_duration=lambda _p: 30.0
    )
    assert not result.allowed


def test_button_reject_edit_submitted_and_garbage(dsc, make_clip):
    cid = make_clip()
    assert discord_bot.handle_button(dsc.store, dsc.config, f"r:{cid}", OWNER)[0] == "Rejected."
    cid2 = make_clip()
    reply, follow = discord_bot.handle_button(dsc.store, dsc.config, f"e:{cid2}", OWNER)
    assert follow == f"edit:{cid2}" and dsc.store.get_clip(cid2)["status"] == "editing"
    assert discord_bot.handle_button(dsc.store, dsc.config, "zzz", OWNER)[0] == "Unknown button."
    assert discord_bot.handle_button(dsc.store, dsc.config, "a:abc", OWNER)[0] == "Unknown button."


def test_store_still_refuses_unknown_approver(dsc, make_clip):
    cid = make_clip()
    dsc.store.mark_previewed(cid, "h", 1)
    with pytest.raises(StoreError):
        dsc.store.approve_clip(cid, "slack:1", "h")


def test_preview_ladder_steps_down_until_it_fits(tmp_path):
    original = tmp_path / "big.mp4"
    original.write_bytes(b"x" * 100)
    sizes = {1000: 60, 700: 40, 450: 20, 300: 5}
    calls = []

    def fake_encode(src, target, height, kbps):
        calls.append(kbps)
        Path(target).write_bytes(b"y" * sizes[kbps])

    out = preview.make_preview(
        original, "abc" * 10, profile="discord", limit_bytes=25, out_dir=tmp_path / "p", encoder=fake_encode
    )
    assert calls == [1000, 700, 450] and out.stat().st_size == 20
    with pytest.raises(preview.PreviewError):
        preview.make_preview(
            original, "def" * 10, profile="discord", limit_bytes=1, out_dir=tmp_path / "p2", encoder=fake_encode
        )


def test_small_clip_is_shown_as_is(tmp_path):
    f = tmp_path / "s.mp4"
    f.write_bytes(b"x" * 10)
    assert preview.make_preview(f, "h", profile="discord", limit_bytes=100) == f


def test_discord_preview_limit_is_under_10mb():
    assert discord_notify.MAX_UPLOAD_BYTES < 10 * 1024 * 1024


def test_previews_use_the_notifier_profile(dsc, make_clip, monkeypatch):
    seen = {}

    def fake(original, sha, *, profile, limit_bytes, **kw):
        seen.update(profile=profile, limit=limit_bytes)
        return original

    monkeypatch.setattr(approval, "make_preview", fake)
    make_clip()
    from autoclip.auto.notify import RecordingNotifier

    n = RecordingNotifier()
    n.preview_profile, n.max_upload_bytes = "discord", discord_notify.MAX_UPLOAD_BYTES
    approval.send_pending_previews(dsc.store, n, dsc.config)
    assert seen == {"profile": "discord", "limit": discord_notify.MAX_UPLOAD_BYTES}
