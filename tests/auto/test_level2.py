"""The decided fully automatic mode: config template, level-2 flow behind the full gate, dry run,
Telegram reminders/commands, and the closed MINOR items (immutable approved copy, old-preview
approve, stuck editing, token-safe logging, no local paths in chat)."""

from __future__ import annotations

import logging
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from autoclip.auto import approval, cli, config as config_mod, gate, poster, secrets, tick
from autoclip.auto.config import AutoConfig, example_config_file, init_config
from autoclip.auto.notify import RecordingNotifier, TelegramNotifier, redact_paths
from autoclip.auto.submit import send_reminders
from autoclip.auto.uploadpost import UploadResult
from typer.testing import CliRunner

KW = {"probe_duration": lambda _p: 30.0}
# Real clock on purpose: approval timestamps come from the store's real clock, and the review window
# (auto_approve.delay_minutes) is measured from them. FAR is "everything queued is due".
NOW = datetime.now(UTC).replace(microsecond=0)
FAR = NOW + timedelta(hours=30)


def l2_config(**extra) -> AutoConfig:
    return AutoConfig(
        level=2,
        auto_approve={"enabled": True, "min_qa": 90, "delay_minutes": 60},
        post={"timezone": "UTC", "slots": ["00:00", "23:59"], "start_date": "2026-11-20"},
        upload_post={"manual_platforms": []},
        **extra,
    )


class FakeClient:
    def __init__(self) -> None:
        self.uploads: list[dict] = []

    def upload(self, **kw):
        self.uploads.append(kw)
        platform = kw["platforms"][0]
        return UploadResult(
            f"req-{len(self.uploads)}",
            [{"platform": platform, "success": True, "post_url": f"https://{platform}.test/{len(self.uploads)}"}],
        )

    def status(self, request_id):
        return {"status": "completed", "results": []}

    def history(self, request_id):
        return []


# ---------------------------------------------------------------- config template


def test_template_is_the_decided_mode_and_validates():
    config = AutoConfig.model_validate(
        yaml.safe_load(example_config_file().read_text(encoding="utf-8"))
    )
    assert config.chat == "telegram" and config.level == 2
    assert config.auto_approve.enabled and config.auto_approve.min_qa == 90
    assert config.upload_post.manual_platforms == []
    assert config.level2_active and "level 2 fully automatic" in config.mode_text()
    assert config.submit.reminder_minutes == [20]


def test_code_defaults_stay_fail_closed():
    config = AutoConfig()
    assert config.level == 1 and not config.level2_active and config.chat == "telegram"


def test_init_config_writes_once(tmp_path):
    target = tmp_path / "auto" / "config.yaml"
    assert init_config(target) == target and target.is_file()
    with pytest.raises(FileExistsError):
        init_config(target)
    init_config(target, force=True)
    assert config_mod.load_config(target).level2_active


def test_real_campaign_sidecar_loads():
    from autoclip.auto.campaign_meta import load_auto_campaign

    repo = Path(__file__).resolve().parents[2] / "campaigns"
    auto = load_auto_campaign("kreekcraft-gta6", repo)
    assert auto.meta.budget_usd == 6045 and auto.meta.cap_per_clip_usd == 300
    assert auto.meta.ends_at is None and auto.meta.submit_url.startswith("https://contentrewards.com/c/")
    assert auto.campaign.rate_per_1k_usd == 1.0


# ---------------------------------------------------------------- level 2 flow


def test_level2_posts_without_a_tap_and_pings_with_deadline_url_and_reminder(env, make_clip):
    config = l2_config()
    good = make_clip(qa=95)
    low = make_clip(qa=80)
    notifier, client = RecordingNotifier(), FakeClient()

    tick.post_cycle(env.store, config, notifier, client, now=NOW, gate_kwargs=KW)
    assert env.store.get_clip(low)["status"] == "rejected"  # below min_qa: never sent, never posted
    assert len(notifier.videos) == 1
    _, caption, buttons = notifier.videos[0]
    assert caption.startswith("AUTO-APPROVED")
    assert [b.callback_data for row in buttons for b in row] == [f"r:{good}"]  # veto only
    clip = env.store.get_clip(good)
    assert clip["status"] == "approved" and clip["approved_by"] == "auto:level2"
    posts = env.store.list_posts()
    assert len(posts) == 3
    assert all(datetime.fromisoformat(p["scheduled_for"]) >= NOW + timedelta(minutes=60) for p in posts)
    assert client.uploads == []  # still inside the review window

    far = FAR
    tick.post_cycle(env.store, config, notifier, client, now=far, gate_kwargs=KW)
    assert sorted(u["platforms"][0] for u in client.uploads) == ["instagram", "tiktok", "youtube"]
    approved_path = env.store.get_clip(good)["path"]
    assert all(u["video_path"] == approved_path for u in client.uploads)
    posted = [t for t, _ in notifier.texts if "Posted on" in t and "submit to Content Rewards now" in t]
    assert len(posted) == 3
    assert all("Deadline: " in t and "UTC" in t for t in posted)
    assert any(t.splitlines()[-1] == "https://youtube.test/2" or "youtube.test" in t for t in posted)

    notifier.texts.clear()
    send_reminders(env.store, notifier, far + timedelta(minutes=19), (20,))
    assert not notifier.texts
    send_reminders(env.store, notifier, far + timedelta(minutes=20), (20,))
    assert len(notifier.texts) == 3 and all("/submitted" in t and ".test/" in t for t, _ in notifier.texts)
    send_reminders(env.store, notifier, far + timedelta(minutes=21), (20,))
    assert len(notifier.texts) == 3  # sent once per post
    env.store.mark_submitted(env.store.list_posts()[0]["id"])  # /submitted stops the reminders
    send_reminders(env.store, notifier, far + timedelta(minutes=31), (20,))
    assert [t for t, _ in notifier.texts[3:]].count(notifier.texts[3][0]) == 1
    assert len(notifier.texts) == 5  # "Deadline passed" for the 2 still unsubmitted posts only


def test_level2_clip_that_fails_the_gate_never_uploads(env, make_clip):
    config = l2_config()
    cinematic = make_clip(qa=99, spoiler_level="raw-cinematic")
    notifier, client = RecordingNotifier(), FakeClient()
    tick.post_cycle(env.store, config, notifier, client, now=NOW, gate_kwargs=KW)
    tick.post_cycle(env.store, config, notifier, client, now=FAR, gate_kwargs=KW)
    assert client.uploads == []
    assert env.store.get_clip(cinematic)["status"] != "posted"
    assert any("spoiler level" in e["detail"] for e in env.store.events("gate_denied"))


def test_level2_respects_pause(env, make_clip):
    config = l2_config()
    make_clip(qa=95)
    notifier, client = RecordingNotifier(), FakeClient()
    tick.post_cycle(env.store, config, notifier, client, now=NOW, gate_kwargs=KW)
    env.store.set_paused(True, "test")
    tick.post_cycle(env.store, config, notifier, client, now=FAR, gate_kwargs=KW)
    assert client.uploads == []
    env.store.set_paused(False, "test")
    tick.post_cycle(env.store, config, notifier, client, now=FAR, gate_kwargs=KW)
    assert len(client.uploads) == 3


def test_level2_off_means_human_buttons_and_no_auto_approval(env, make_clip):
    config = AutoConfig(upload_post={"manual_platforms": []})  # level 1
    clip = make_clip(qa=95)
    notifier = RecordingNotifier()
    tick.post_cycle(env.store, config, notifier, FakeClient(), now=NOW, gate_kwargs=KW)
    assert env.store.get_clip(clip)["status"] == "pending_approval"
    labels = [b.text for row in notifier.videos[0][2] for b in row]
    assert labels == ["Approve", "Reject", "Edit hook"]


# ---------------------------------------------------------------- dry run


def queue_level2_post(env, make_clip, config):
    clip = make_clip(qa=95)
    notifier = RecordingNotifier()
    tick.post_cycle(env.store, config, notifier, FakeClient(), now=NOW, gate_kwargs=KW)
    return clip, notifier


def test_dry_run_pings_would_post_and_never_uploads(env, make_clip):
    config = l2_config()
    clip, notifier = queue_level2_post(env, make_clip, config)
    client = FakeClient()
    far = FAR
    summary = tick.post_cycle(env.store, config, notifier, client, now=far, gate_kwargs=KW, dry_run=True)
    assert summary["would_post"] == 3 and "posted" not in summary
    would = [t for t, _ in notifier.texts if t.startswith("WOULD POST")]
    assert len(would) == 3 and all("nothing was uploaded" in t for t in would)
    assert client.uploads == []
    assert {p["status"] for p in env.store.list_posts()} == {"queued"}  # nothing claimed or posted
    assert env.store.get_clip(clip)["status"] == "approved"
    tick.post_cycle(env.store, config, notifier, client, now=far, gate_kwargs=KW, dry_run=True)
    assert len([t for t, _ in notifier.texts if t.startswith("WOULD POST")]) == 3  # once per post
    # switching to live afterwards posts the very same queue
    tick.post_cycle(env.store, config, notifier, client, now=far, gate_kwargs=KW)
    assert len(client.uploads) == 3


def test_dry_run_reports_what_the_gate_would_block(env, make_clip):
    config = l2_config()
    clip, notifier = queue_level2_post(env, make_clip, config)
    env.store.set_paused(True, "test")
    tick.post_cycle(env.store, config, notifier, FakeClient(), now=FAR,
                    gate_kwargs=KW, dry_run=True)  # fmt: skip
    blocked = [t for t, _ in notifier.texts if t.startswith("WOULD NOT POST")]
    assert len(blocked) == 3 and all("paused" in t for t in blocked)


def test_cli_tick_dry_run_flag_passes_no_client(env, monkeypatch):
    seen = {}

    def fake_tick(store, config, notifier, **kw):
        seen.update(kw)
        return {"ok": True}

    monkeypatch.setattr(tick, "tick", fake_tick)
    monkeypatch.setattr(cli, "_notifier", lambda config=None: RecordingNotifier())
    result = CliRunner().invoke(cli.app, ["tick", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert seen["dry_run"] is True and seen["client"] is None
    CliRunner().invoke(cli.app, ["tick"])
    assert seen["dry_run"] is False


def test_cli_init_config(env):
    result = CliRunner().invoke(cli.app, ["init-config"])
    assert result.exit_code == 0 and config_mod.config_file().is_file()
    assert CliRunner().invoke(cli.app, ["init-config"]).exit_code == 1  # no silent overwrite
    assert CliRunner().invoke(cli.app, ["init-config", "--force"]).exit_code == 0


def test_status_shows_the_mode(env, make_clip):
    assert "Mode: level 2 fully automatic" in approval.status_text(env.store, l2_config())
    assert "Mode: level 1" in approval.status_text(env.store, AutoConfig())


# ---------------------------------------------------------------- /submitted


def test_submitted_command_text(env, make_clip):
    config = l2_config()
    make_clip(qa=95)
    notifier, client = RecordingNotifier(), FakeClient()
    assert approval.submitted_text(env.store) == "Nothing is waiting for submission."
    tick.post_cycle(env.store, config, notifier, client, now=NOW, gate_kwargs=KW)
    tick.post_cycle(env.store, config, notifier, client, now=FAR, gate_kwargs=KW)
    listing = approval.submitted_text(env.store)
    assert "Several posts" in listing and ".test/" in listing
    url = next(p for p in env.store.list_posts())["results"]
    first_url = next(iter(url.values()))["url"]
    assert approval.submitted_text(env.store, first_url).startswith("Logged post")
    assert approval.submitted_text(env.store, "https://nope.test/x").startswith("No posted clip")
    assert len(env.store.awaiting_submission()) == 2


# ---------------------------------------------------------------- immutable approved copy


def approve_by_owner(env, clip_id):
    clip = env.store.get_clip(clip_id)
    notifier = RecordingNotifier()
    approval.send_pending_previews(env.store, notifier, env.config)
    return approval.approve(env.store, clip_id, 123, env.config)


def test_approved_clip_is_frozen_as_sha_named_read_only_copy(env, make_clip):
    clip_id = make_clip()
    original = Path(env.store.get_clip(clip_id)["path"])
    assert approve_by_owner(env, clip_id) == "Approved."
    clip = env.store.get_clip(clip_id)
    copy = Path(clip["path"])
    assert copy != original and copy.name == f"{clip['approved_sha256']}.mp4"
    assert copy.parent == approval.approved_dir()
    assert copy.read_bytes() == original.read_bytes() and gate.sha256_file(copy) == clip["approved_sha256"]
    assert not os.access(copy, os.W_OK) or not (copy.stat().st_mode & stat.S_IWRITE)
    # the original can change afterwards: the approved copy (what gets uploaded) does not
    original.write_bytes(b"swapped after approval")
    assert gate.sha256_file(copy) == clip["approved_sha256"]
    decision = gate.check_post_allowed(env.store, clip_id, config=env.config, platforms=["youtube"], **KW)
    assert decision.allowed, decision.reasons


def test_tampering_with_the_approved_copy_is_still_denied(env, make_clip):
    clip_id = make_clip()
    approve_by_owner(env, clip_id)
    copy = Path(env.store.get_clip(clip_id)["path"])
    copy.chmod(0o666)
    copy.write_bytes(b"tampered")
    decision = gate.check_post_allowed(env.store, clip_id, config=env.config, platforms=["youtube"], **KW)
    assert not decision.allowed and any("changed after approval" in r for r in decision.reasons)


def test_file_changed_between_preview_and_approval_is_not_approved(env, make_clip):
    clip_id = make_clip()
    approval.send_pending_previews(env.store, RecordingNotifier(), env.config)
    Path(env.store.get_clip(clip_id)["path"]).write_bytes(b"edited after the preview")
    assert "file changed" in approval.approve(env.store, clip_id, 123, env.config)
    assert env.store.get_clip(clip_id)["status"] == "pending_approval"


# ---------------------------------------------------------------- old preview / stuck editing


def test_old_preview_button_cannot_approve_a_newer_version(env, make_clip, tmp_path):
    clip_id = make_clip()
    notifier = RecordingNotifier()
    approval.send_pending_previews(env.store, notifier, env.config)
    old_token = approval.preview_token(env.store.get_clip(clip_id))
    assert notifier.videos[0][2][0][0].callback_data == f"a:{clip_id}:{old_token}"

    assert approval.begin_edit_hook(env.store, clip_id).startswith("Send")

    def rerender(clip, hook):
        new = tmp_path / "rerendered.mp4"
        new.write_bytes(b"new version with a new hook")
        return new

    assert "Hook updated" in approval.apply_hook_edit(env.store, clip_id, "New hook", rerender)
    approval.send_pending_previews(env.store, notifier, env.config)
    new_token = approval.preview_token(env.store.get_clip(clip_id))
    assert new_token != old_token
    assert "out of date" in approval.approve(env.store, clip_id, 123, env.config, token=old_token)
    assert env.store.get_clip(clip_id)["status"] == "pending_approval"
    assert approval.approve(env.store, clip_id, 123, env.config, token=new_token) == "Approved."


def test_discord_button_with_stale_token_is_refused(env, make_clip):
    from autoclip.auto import discord_bot

    clip_id = make_clip()
    approval.send_pending_previews(env.store, RecordingNotifier(), env.config)
    reply, _ = discord_bot.handle_button(env.store, env.config, f"a:{clip_id}:deadbeef0000", "123")
    assert "out of date" in reply


def test_clip_stuck_in_editing_goes_back_to_review(env, make_clip):
    clip_id = make_clip()
    approval.send_pending_previews(env.store, RecordingNotifier(), env.config)
    approval.begin_edit_hook(env.store, clip_id)
    assert env.store.get_clip(clip_id)["status"] == "editing"
    assert approval.restore_stale_edits(env.store, datetime.now(UTC) + timedelta(minutes=5)) == 0
    soon_after = datetime.now(UTC) + timedelta(minutes=11)
    tick.post_cycle(env.store, env.config, RecordingNotifier(), FakeClient(), now=soon_after, gate_kwargs=KW)
    assert env.store.get_clip(clip_id)["status"] == "pending_approval"
    assert env.store.events("edit_timeout")


# ---------------------------------------------------------------- token-safe logging, no paths


def test_httpx_logs_never_contain_the_telegram_token(env, caplog):
    logging.getLogger("httpx").setLevel(logging.INFO)  # someone raises it ...
    secrets.harden_logging()  # ... and the CLI/bot entry points force it back
    caplog.set_level(logging.DEBUG)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"result": {"message_id": 5}}))
    TelegramNotifier(httpx.Client(transport=transport)).send_text("hello")
    assert "123:fake" not in caplog.text and "api.telegram.org" not in caplog.text
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


def test_importing_the_package_hardens_logging():
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    secrets.harden_logging()
    assert logging.getLogger("httpx").level == logging.WARNING


def test_redact_paths_keeps_urls_and_removes_local_paths():
    assert redact_paths(r"file C:\Users\ahmad\.autoclip\exports\x.mp4 done") == "file <path> done"
    assert redact_paths("copy at C:/Users/ahmad/clip.mp4") == "copy at <path>"
    assert redact_paths(r"\\server\share\clip.mp4") == "<path>"
    assert redact_paths("see /home/ahmad/x.mp4 now") == "see <path> now"
    url = "https://www.tiktok.com/@crazy_heist/video/123 and https://x.test/home/a"
    assert redact_paths(url) == url


def test_hand_post_message_has_no_local_path(env, make_clip):
    env.config.upload_post.manual_platforms = ["tiktok"]
    clip_id = make_clip()
    approve_by_owner(env, clip_id)
    notifier = RecordingNotifier()
    now = datetime.now(UTC)
    env.store.enqueue_post(clip_id, now - timedelta(minutes=1), ["tiktok"])
    poster.post_due(env.store, env.config, notifier, FakeClient(), now=now, gate_kwargs=KW,
                    sleep=lambda s: None)  # fmt: skip
    sent = [c for _, c, _ in notifier.videos] + [t for t, _ in notifier.texts]
    assert any("POST BY HAND" in text for text in sent)
    for text in sent:
        assert str(env.tmp) not in text and "Full-quality file" not in text and ".mp4" not in text


def test_error_text_with_a_path_is_redacted_in_the_chat(env):
    notifier = RecordingNotifier()
    notifier.send_text(rf"Post 3 failed: cannot open {env.tmp}\clip.mp4")
    assert str(env.tmp) not in notifier.texts[0][0]
