"""Offline approval tests using real SQLite state and recorded notifications."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from autoclip.auto import approval
from autoclip.auto.config import AutoConfig
from autoclip.auto.gate import sha256_file
from autoclip.auto.notify import RecordingNotifier
from autoclip.auto.store import Store


@pytest.fixture
def clip_store(tmp_path):
    store = Store(tmp_path / "auto.db")
    job_id = store.add_job(campaign_key="campaign", vod_id="vod")
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake mp4")
    clip_id = store.add_clip(
        job_id=job_id,
        campaign_key="campaign",
        title="Title",
        hook="Hook",
        caption="Caption",
        hashtags=["#gta6"],
        qa_score=90,
        layout="reaction",
        path=str(path),
    )
    return store, clip_id, path


def test_preview_once_with_buttons_and_original_hash(clip_store):
    store, clip_id, path = clip_store
    notifier = RecordingNotifier()
    config = AutoConfig()
    assert approval.send_pending_previews(store, notifier, config) == 1
    assert approval.send_pending_previews(store, notifier, config) == 0
    assert len(notifier.videos) == 1
    video, caption, buttons = notifier.videos[0]
    assert video == path
    for part in ("Title", "Hook", "Caption", "#gta6", "90", "reaction", "none", "campaign"):
        assert part in caption
    assert [[b.callback_data for b in row] for row in buttons] == [
        [f"a:{clip_id}", f"r:{clip_id}"],
        [f"e:{clip_id}"],
    ]
    clip = store.get_clip(clip_id)
    assert clip["previewed_sha256"] == sha256_file(path)
    assert clip["preview_message_id"] == 101


def test_low_qa_rejected_without_preview(clip_store):
    store, clip_id, _ = clip_store
    store.update_clip(clip_id, qa_score=20)
    notifier = RecordingNotifier()
    assert approval.send_pending_previews(store, notifier, AutoConfig()) == 0
    assert notifier.videos == []
    assert store.get_clip(clip_id)["status"] == "rejected"
    assert len(store.events("low_qa_skipped")) == 1


def test_missing_file_skipped(clip_store):
    store, clip_id, path = clip_store
    store.update_clip(clip_id, path=str(path.with_name("missing.mp4")))
    assert approval.send_pending_previews(store, RecordingNotifier(), AutoConfig()) == 0
    assert store.events("preview_missing_file")
    assert store.get_clip(clip_id)["previewed_at"] is None


def test_approve_records_identity_and_hash(clip_store):
    store, clip_id, path = clip_store
    config = AutoConfig()
    approval.send_pending_previews(store, RecordingNotifier(), config)
    assert approval.approve(store, clip_id, 42, config) == "Approved."
    clip = store.get_clip(clip_id)
    assert clip["status"] == "approved"
    assert clip["approved_by"] == "telegram:42"
    assert clip["approved_sha256"] == sha256_file(path)
    assert store.list_posts() == []
    assert approval.approve(store, clip_id, 42, config).startswith("Cannot approve")


def test_changed_file_refused_without_resend(clip_store):
    store, clip_id, path = clip_store
    notifier = RecordingNotifier()
    approval.send_pending_previews(store, notifier, AutoConfig())
    path.write_bytes(b"changed")
    assert "changed" in approval.approve(store, clip_id, 42, AutoConfig())
    assert store.get_clip(clip_id)["status"] == "pending_approval"
    assert approval.send_pending_previews(store, notifier, AutoConfig()) == 0
    assert len(notifier.videos) == 1


def test_reject(clip_store):
    store, clip_id, _ = clip_store
    assert approval.reject(store, clip_id, 42) == "Rejected."
    assert store.get_clip(clip_id)["status"] == "rejected"
    assert store.get_clip(clip_id)["rejected_at"]


def test_edit_requires_fresh_preview(clip_store):
    store, clip_id, path = clip_store
    notifier = RecordingNotifier()
    approval.send_pending_previews(store, notifier, AutoConfig())
    approval.begin_edit_hook(store, clip_id)
    assert store.get_clip(clip_id)["status"] == "editing"
    rendered = path.with_name("edited.mp4")
    rendered.write_bytes(b"new render")
    rerender = Mock(return_value=rendered)
    assert "updated" in approval.apply_hook_edit(store, clip_id, "New hook", rerender)
    assert rerender.call_args.args[0]["id"] == clip_id
    assert rerender.call_args.args[1] == "New hook"
    clip = store.get_clip(clip_id)
    assert clip["hook"] == "New hook"
    assert clip["path"] == str(rendered)
    assert clip["status"] == "pending_approval"
    assert clip["previewed_at"] is None
    assert clip["previewed_sha256"] == ""
    assert "Cannot approve" in approval.approve(store, clip_id, 42, AutoConfig())
    assert approval.send_pending_previews(store, notifier, AutoConfig()) == 1
    assert approval.approve(store, clip_id, 42, AutoConfig()) == "Approved."


@pytest.mark.parametrize("hook", ["", " " * 5, "x" * 61, "a\nb", "a\rb"])
def test_invalid_hook_does_not_rerender(clip_store, hook):
    store, clip_id, _ = clip_store
    approval.begin_edit_hook(store, clip_id)
    rerender = Mock()
    assert "must be" in approval.apply_hook_edit(store, clip_id, hook, rerender)
    rerender.assert_not_called()
    assert store.get_clip(clip_id)["status"] == "editing"


@pytest.mark.parametrize("raises", [False, True])
def test_failed_edit_restores_original(clip_store, raises):
    store, clip_id, path = clip_store
    approval.send_pending_previews(store, RecordingNotifier(), AutoConfig())
    approval.begin_edit_hook(store, clip_id)
    rerender = Mock(side_effect=RuntimeError("failed")) if raises else Mock(return_value=None)
    assert "failed" in approval.apply_hook_edit(store, clip_id, "New", rerender)
    clip = store.get_clip(clip_id)
    assert clip["status"] == "pending_approval"
    assert clip["path"] == str(path)
    assert clip["hook"] == "Hook"
    assert clip["previewed_sha256"] == sha256_file(path)


def test_large_preview_hash_is_original(clip_store, monkeypatch):
    from autoclip.auto import preview

    store, clip_id, path = clip_store
    monkeypatch.setattr(preview, "ffmpeg_path", lambda: "ffmpeg-test")

    def transcode(command, **kwargs):
        assert command[0] == "ffmpeg-test"
        assert command[command.index("-i") + 1] == str(path)
        Path(command[-1]).write_bytes(b"tiny")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(preview.subprocess, "run", transcode)
    notifier = RecordingNotifier()
    notifier.max_upload_bytes = 4  # smaller than the clip, so a preview copy is needed
    assert approval.send_pending_previews(store, notifier, AutoConfig()) == 1
    shown = notifier.videos[0][0]
    assert shown.parent.name == "previews"
    assert store.get_clip(clip_id)["previewed_sha256"] == sha256_file(path)
    assert sha256_file(shown) != sha256_file(path)


def test_status_text_reports_counts_schedule_events_without_details(clip_store):
    store, clip_id, _ = clip_store
    config = AutoConfig()
    approval.send_pending_previews(store, RecordingNotifier(), config)
    approval.approve(store, clip_id, 42, config)
    now = datetime.now(UTC)
    post_id = store.enqueue_post(clip_id, now, ["youtube"])
    store.set_paused(True, "telegram")
    store.log_event("safe_kind", "secret-value-must-not-be-shown")
    text = approval.status_text(store, config)
    for part in ("paused", "approved: 1", "Queued today: 1", "Posted today: 0", "safe_kind"):
        assert part in text
    assert "secret-value" not in text
    assert "Next queued: none" not in text
    store.finish_post(post_id, request_id="req", results={}, posted_at=now, submit_deadline=None)
    text = approval.status_text(store, config)
    assert "Posted today: 1" in text
    assert "Next queued: none" in text
