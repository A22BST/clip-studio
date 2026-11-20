"""Posting safety, scheduling, recovery and submission reminders, without network."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from autoclip.auto import gate
from autoclip.auto.notify import Button, RecordingNotifier
from autoclip.auto.poster import next_slot, post_due, refresh_urls, schedule_approved
from autoclip.auto.store import parse_iso
from autoclip.auto.submit import send_reminders
from autoclip.auto.uploadpost import UploadPostClient, UploadPostError, UploadResult

KW = {"probe_duration": lambda p: 30.0}


class FakeClient:
    def __init__(self):
        self.uploads = []
        self.polls = 0
        self.error = None
        self.pending = False

    def upload(self, **kwargs):
        self.uploads.append(kwargs)
        if self.error:
            raise self.error
        return UploadResult("request-1", [])

    def status(self, request_id):
        self.polls += 1
        if self.pending:
            return {"status": "processing", "results": []}
        return {
            "status": "completed",
            "results": [{"platform": "tiktok", "success": True, "post_url": "https://post.test/1"}],
        }

    def history(self, request_id):
        return []


def run(env, notifier, client, now):
    return post_due(
        env.store,
        env.config,
        notifier,
        client,
        now=now,
        campaigns_dir=env.campaigns,
        gate_kwargs=KW,
        sleep=lambda _: None,
    )


def queue(env, make_clip, now):
    cid = make_clip(approve=True)
    return cid, env.store.enqueue_post(cid, now, ["tiktok"])


@pytest.mark.parametrize("denial", ["unapproved", "paused", "changed", "inactive", "gate_error"])
def test_safety_never_uploads(env, make_clip, monkeypatch, denial):
    now = datetime.now(UTC)
    cid, pid = queue(env, make_clip, now)
    if denial == "unapproved":
        # Simulate stale/externally corrupted queue state to exercise the gate too.
        with env.store._conn() as con:
            con.execute("UPDATE clips SET status='pending_approval' WHERE id=?", (cid,))
    elif denial == "paused":
        env.store.set_paused(True)
    elif denial == "changed":
        Path(env.store.get_clip(cid)["path"]).write_bytes(b"changed")
    elif denial == "inactive":
        (env.campaigns / "auto/test-campaign.yaml").write_text("active: false\n")
    else:

        def broken(*args, **kwargs):
            raise RuntimeError("broken gate")

        monkeypatch.setattr(gate, "check_post_allowed", broken)
    client, notifier = FakeClient(), RecordingNotifier()
    assert run(env, notifier, client, now) == []
    assert client.uploads == []
    assert env.store.get_post(pid)["status"] == ("queued" if denial == "paused" else "cancelled")


def test_pause_resume_and_idempotency(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    notifier, client = RecordingNotifier(), FakeClient()
    env.store.set_paused(True)
    run(env, notifier, client, now)
    assert parse_iso(env.store.get_post(pid)["scheduled_for"]) == now.replace(microsecond=0)
    env.store.set_paused(False)
    assert run(env, notifier, client, now) == [pid]
    assert run(env, notifier, client, now) == []
    assert len(client.uploads) == 1


def test_happy_path_real_http_client(env, make_clip):
    now = datetime.now(UTC)
    cid, pid = queue(env, make_clip, now)
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "request_id": "r"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "results": [
                    {"platform": "tiktok", "success": True, "post_url": "https://post.test/happy"}
                ],
            },
        )

    client = UploadPostClient(httpx.Client(transport=httpx.MockTransport(handler)))
    notifier = RecordingNotifier()
    assert run(env, notifier, client, now) == [pid]
    assert calls[0].headers["Idempotency-Key"] == f"clip-{cid}-post-{pid}"
    assert len(calls) == 2
    post = env.store.get_post(pid)
    assert post["status"] == "posted"
    assert env.store.get_clip(cid)["status"] == "posted"
    assert parse_iso(post["submit_deadline"]) == (now + timedelta(minutes=30)).replace(
        microsecond=0
    )
    text, buttons = notifier.texts[-1]
    assert "https://post.test/happy" in text
    assert "Posted. SUBMIT TO THE CAMPAIGN NOW: deadline" in text
    assert "(30 min)" in text
    assert buttons[0][0].url == "https://example.test/submit"
    assert buttons[1][0].callback_data == f"s:{pid}"


def test_claim_precedes_gate_and_competing_claim_blocks(env, make_clip, monkeypatch):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    original = gate.check_post_allowed

    def check(*args, **kwargs):
        assert env.store.get_post(pid)["status"] == "posting"
        return original(*args, **kwargs)

    monkeypatch.setattr(gate, "check_post_allowed", check)
    assert env.store.claim_post(pid)
    client = FakeClient()
    assert run(env, RecordingNotifier(), client, now) == []
    assert not client.uploads
    env.store.release_post(pid)
    assert run(env, RecordingNotifier(), client, now) == [pid]


def test_pending_urls_refresh_once(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    client, notifier = FakeClient(), RecordingNotifier()
    client.pending = True
    sleeps = []
    post_due(env.store, env.config, notifier, client, now=now, gate_kwargs=KW, sleep=sleeps.append)
    assert sum(sleeps) == 240
    assert env.store.get_post(pid)["request_id"] == "request-1"
    client.pending = False
    run(env, notifier, client, now)
    run(env, notifier, client, now)
    assert len(client.uploads) == 1
    assert len(notifier.texts) == 2
    assert "https://post.test/1" in notifier.texts[-1][0]


def test_history_fills_delayed_link(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    client, notifier = FakeClient(), RecordingNotifier()
    client.pending = True
    run(env, notifier, client, now)
    client.history = lambda _: [{"platform": "tiktok", "post_url": "https://late.test/1"}]
    refresh_urls(env.store, client, notifier)
    refresh_urls(env.store, client, notifier)
    assert env.store.get_post(pid)["results"]["tiktok"]["url"] == "https://late.test/1"
    assert len(notifier.texts) == 2


def test_retry_three_times_then_fail(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    client, notifier = FakeClient(), RecordingNotifier()
    client.error = UploadPostError("transport error", retryable=True)
    for attempt in range(3):
        run(env, notifier, client, now + timedelta(minutes=15 * attempt))
        assert env.store.get_post(pid)["attempts"] == attempt + 1
    assert env.store.get_post(pid)["status"] == "failed"
    assert len(notifier.texts) == 1
    assert len(client.uploads) == 3


def test_error_with_known_request_polls_without_resend(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    client = FakeClient()
    client.error = UploadPostError("ambiguous", request_id="known", retryable=True)
    assert run(env, RecordingNotifier(), client, now) == [pid]
    assert run(env, RecordingNotifier(), client, now) == []
    assert len(client.uploads) == 1
    assert env.store.get_post(pid)["request_id"] == "known"


def test_recovers_persisted_request(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    env.store.claim_post(pid)
    with env.store._conn() as con:
        con.execute("UPDATE posts SET request_id='known' WHERE id=?", (pid,))
    client = FakeClient()
    assert run(env, RecordingNotifier(), client, now) == [pid]
    assert not client.uploads


def test_next_slot_gap_cap_and_days(env, make_clip):
    env.config.post.timezone = "UTC"
    env.config.post.slots = ["11:00", "12:00", "14:00"]
    env.config.post.max_per_day = 2
    env.config.post.min_gap_minutes = 90
    now = datetime(2026, 11, 20, 11, tzinfo=UTC)
    assert next_slot(env.store, env.config, now) == now
    for day in range(3):
        first = now + timedelta(days=day)
        assert next_slot(env.store, env.config, now) == first
        env.store.enqueue_post(make_clip(approve=True), first, ["tiktok"])
        second = first + timedelta(hours=3)
        assert next_slot(env.store, env.config, now) == second
        env.store.enqueue_post(make_clip(approve=True), second, ["tiktok"])
    assert next_slot(env.store, env.config, now) == now + timedelta(days=3)


def test_schedule_intersection_delay_and_no_duplicate(env, make_clip):
    now = datetime.now(UTC)
    env.config.post.timezone = "UTC"
    env.config.post.platforms = ["tiktok"]
    cid = make_clip()
    digest = gate.sha256_file(Path(env.store.get_clip(cid)["path"]))
    env.store.mark_previewed(cid, digest)
    env.store.approve_clip(cid, "auto:level2", digest)
    posts = schedule_approved(env.store, env.config, now)
    assert len(posts) == 1
    post = env.store.get_post(posts[0])
    assert post["platforms"] == ["tiktok"]
    assert parse_iso(post["scheduled_for"]) >= parse_iso(
        env.store.get_clip(cid)["approved_at"]
    ) + timedelta(minutes=60)
    assert schedule_approved(env.store, env.config, now) == []


def test_schedule_empty_platforms_logs(env, make_clip):
    make_clip(approve=True)
    env.config.post.platforms = []
    assert schedule_approved(env.store, env.config) == []
    assert env.store.events("schedule_skipped")


def test_reminder_timing_and_submission(env, make_clip):
    now = datetime.now(UTC).replace(microsecond=0)
    _, pid = queue(env, make_clip, now)
    notifier = RecordingNotifier()
    run(env, notifier, FakeClient(), now)
    notifier.texts.clear()
    for minutes, expected in [
        (9, 0),
        (10, 1),
        (10, 1),
        (19, 1),
        (20, 2),
        (20, 2),
        (30, 3),
        (31, 3),
    ]:
        send_reminders(env.store, notifier, now + timedelta(minutes=minutes))
        assert len(notifier.texts) == expected
    assert "20 min left to submit" in notifier.texts[0][0]
    assert "10 min left to submit" in notifier.texts[1][0]
    assert "Deadline passed" in notifier.texts[2][0]
    assert notifier.texts[0][1][-1][0].callback_data == f"s:{pid}"
    assert env.store.get_post(pid)["reminders_sent"] == 3


def test_submitted_posts_have_no_reminders(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    notifier = RecordingNotifier()
    run(env, notifier, FakeClient(), now)
    env.store.mark_submitted(pid)
    notifier.texts.clear()
    send_reminders(env.store, notifier, now + timedelta(minutes=40))
    assert not notifier.texts


def test_empty_gate_denial_fails_closed(env, make_clip, monkeypatch):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    monkeypatch.setattr(gate, "check_post_allowed", lambda *a, **k: gate.GateResult(False))
    client = FakeClient()
    run(env, RecordingNotifier(), client, now)
    assert not client.uploads
    assert env.store.get_post(pid)["status"] == "cancelled"


def test_skipped_platform_is_reported_without_waiting(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    client = FakeClient()
    client.status = lambda _: {
        "results": [
            {
                "platform": "tiktok",
                "success": False,
                "skip_reason": "profile_platform_not_configured",
            }
        ]
    }
    notifier = RecordingNotifier()
    assert run(env, notifier, client, now) == [pid]
    result = env.store.get_post(pid)["results"]["tiktok"]
    assert result["skipped"]
    assert result["success"] is None
    assert "profile_platform_not_configured" in notifier.texts[-1][0]


@pytest.mark.parametrize("status", [403, 429])
def test_permanent_errors_fail_without_retry(env, make_clip, status):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    client = FakeClient()
    client.error = UploadPostError("permanent", status_code=status)
    notifier = RecordingNotifier()
    run(env, notifier, client, now)
    run(env, notifier, client, now + timedelta(minutes=15))
    assert len(client.uploads) == 1
    assert env.store.get_post(pid)["status"] == "failed"
    assert "failed" in notifier.texts[-1][0]


def test_known_request_status_errors_never_resend(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    client = FakeClient()

    def unavailable(_):
        raise UploadPostError("status timeout", retryable=True)

    client.status = unavailable
    notifier = RecordingNotifier()
    run(env, notifier, client, now)
    run(env, notifier, client, now + timedelta(minutes=15))
    assert len(client.uploads) == 1
    assert env.store.get_post(pid)["status"] == "posted"


def test_dst_nonexistent_slot_is_skipped(env):
    env.config.post.timezone = "Europe/Copenhagen"
    env.config.post.slots = ["02:30", "04:00"]
    now = datetime(2026, 3, 29, 0, tzinfo=UTC)
    assert next_slot(env.store, env.config, now) == datetime(2026, 3, 29, 2, tzinfo=UTC)


def test_local_day_cap_crosses_utc_midnight(env, make_clip):
    env.config.post.timezone = "Europe/Copenhagen"
    env.config.post.slots = ["00:00", "04:00"]
    env.config.post.max_per_day = 1
    first = datetime(2026, 11, 19, 23, tzinfo=UTC)
    env.store.enqueue_post(make_clip(approve=True), first, ["tiktok"])
    assert next_slot(env.store, env.config, first) == first + timedelta(days=1)


def test_deadline_after_missed_ticks_is_sent_once(env, make_clip):
    now = datetime.now(UTC)
    _, pid = queue(env, make_clip, now)
    notifier = RecordingNotifier()
    run(env, notifier, FakeClient(), now)
    notifier.texts.clear()
    send_reminders(env.store, notifier, now + timedelta(minutes=40))
    send_reminders(env.store, notifier, now + timedelta(minutes=40))
    assert len(notifier.texts) == 1
    assert "Deadline passed" in notifier.texts[0][0]
    assert env.store.get_post(pid)["reminders_sent"] == 3


def test_buttons_omit_empty_campaign_url(env, make_clip):
    now = datetime.now(UTC)
    (env.campaigns / "auto/test-campaign.yaml").write_text("active: true\n")
    _, pid = queue(env, make_clip, now)
    notifier = RecordingNotifier()
    run(env, notifier, FakeClient(), now)
    assert notifier.texts[-1][1] == [[Button("Submitted", callback_data=f"s:{pid}")]]


def test_manual_platform_is_not_uploaded_and_sent_by_hand(env, make_clip):
    """Free Upload-Post plan: no TikTok. YouTube posts by API, TikTok goes to chat as file + text."""
    env.config.upload_post.manual_platforms = ["tiktok"]
    clip_id = make_clip(approve=True)
    now = datetime.now(UTC)
    env.store.enqueue_post(clip_id, now - timedelta(minutes=1), ["tiktok", "youtube"])
    client, notifier = FakeClient(), RecordingNotifier()
    client.status = lambda rid: {
        "status": "completed",
        "results": [{"platform": "youtube", "success": True, "post_url": "https://yt.test/1"}],
    }
    run(env, notifier, client, now)
    assert client.uploads[0]["platforms"] == ["youtube"]  # TikTok never reaches the API
    post = env.store.list_posts("posted")[0]
    assert post["results"]["youtube"]["url"] == "https://yt.test/1"
    assert post["results"]["tiktok"]["message"] == "post by hand"
    hand = [v for v in notifier.videos if "POST BY HAND on tiktok" in v[1]]
    assert hand and "Insane moment" in hand[0][1] and "#GTA6" in hand[0][1]


def test_only_manual_platforms_makes_no_api_call(env, make_clip):
    env.config.upload_post.manual_platforms = ["tiktok"]
    clip_id = make_clip(approve=True)
    now = datetime.now(UTC)
    env.store.enqueue_post(clip_id, now - timedelta(minutes=1), ["tiktok"])
    client, notifier = FakeClient(), RecordingNotifier()
    run(env, notifier, client, now)
    assert client.uploads == [] and client.polls == 0
    assert env.store.list_posts("posted") and any("POST BY HAND" in v[1] for v in notifier.videos)
