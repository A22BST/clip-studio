"""The safety core: store state machine and the post gate. Every denial path is tested."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from autoclip.auto import gate
from autoclip.auto.config import AutoConfig
from autoclip.auto.store import Store, StoreError

CHAT = "123"
KW = {"probe_duration": lambda _p: 30.0}


def check(env, clip_id, **over):
    kw = dict(config=env.config, platforms=["tiktok"], **KW) | over
    return gate.check_post_allowed(env.store, clip_id, **kw)


# -- store ------------------------------------------------------------------------------
def test_approve_requires_previewed_hash(env, make_clip):
    cid = make_clip()
    with pytest.raises(StoreError):
        env.store.approve_clip(cid, f"telegram:{CHAT}", "deadbeef")  # never previewed
    env.store.mark_previewed(cid, "abc", 1)
    with pytest.raises(StoreError):
        env.store.approve_clip(cid, f"telegram:{CHAT}", "different")  # file changed
    env.store.approve_clip(cid, f"telegram:{CHAT}", "abc")
    assert env.store.get_clip(cid)["status"] == "approved"


def test_approver_must_be_telegram_or_level2(env, make_clip):
    cid = make_clip()
    env.store.mark_previewed(cid, "abc", 1)
    with pytest.raises(StoreError):
        env.store.approve_clip(cid, "someone", "abc")


def test_status_cannot_jump_to_approved_or_back(env, make_clip):
    cid = make_clip()
    with pytest.raises(StoreError):
        env.store.set_clip_status(cid, "approved")
    with pytest.raises(StoreError):
        env.store.set_clip_status(cid, "posted")
    env.store.set_clip_status(cid, "rejected")
    with pytest.raises(StoreError):
        env.store.set_clip_status(cid, "pending_approval")


def test_cannot_queue_post_for_unapproved_clip(env, make_clip):
    cid = make_clip()
    with pytest.raises(StoreError):
        env.store.enqueue_post(cid, datetime.now(UTC), ["tiktok"])


def test_claim_post_is_atomic_and_one_post_per_clip(env, make_clip):
    cid = make_clip(approve=True)
    pid = env.store.enqueue_post(cid, datetime.now(UTC) - timedelta(minutes=1), ["tiktok"])
    with pytest.raises(StoreError):
        env.store.enqueue_post(cid, datetime.now(UTC), ["tiktok"])
    assert env.store.claim_post(pid) is True
    assert env.store.claim_post(pid) is False


def test_rejecting_cancels_queued_posts(env, make_clip):
    cid = make_clip(approve=True)
    pid = env.store.enqueue_post(cid, datetime.now(UTC), ["tiktok"])
    env.store.set_clip_status(cid, "rejected")
    assert env.store.get_post(pid)["status"] == "cancelled"


def test_job_dedupe_and_claim(env):
    a = env.store.add_job(campaign_key="c", vod_id="1", start_s=0, end_s=0)
    assert env.store.add_job(campaign_key="c", vod_id="1", start_s=0, end_s=0) is None
    assert env.store.claim_next_job()["id"] == a
    assert env.store.claim_next_job() is None


# -- gate -------------------------------------------------------------------------------
def test_gate_allows_a_clean_approved_clip(env, make_clip):
    cid = make_clip(approve=True)
    assert check(env, cid).allowed, check(env, cid).reasons


def test_gate_denies_unapproved(env, make_clip):
    assert not check(env, make_clip())


def test_gate_denies_when_paused_and_allows_after_resume(env, make_clip):
    cid = make_clip(approve=True)
    env.store.set_paused(True, "test")
    result = check(env, cid)
    assert not result and "paused" in result.reasons[0]
    env.store.set_paused(False, "test")
    assert check(env, cid)


def test_gate_denies_changed_file(env, make_clip):
    cid = make_clip(approve=True)
    open(env.store.get_clip(cid)["path"], "ab").write(b"tampered")
    assert any("changed" in r for r in check(env, cid).reasons)


def test_gate_denies_missing_file(env, make_clip):
    cid = make_clip(approve=True)
    import os

    os.remove(env.store.get_clip(cid)["path"])
    assert not check(env, cid)


def test_gate_denies_wrong_chat(env, make_clip, monkeypatch):
    cid = make_clip(approve=True)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    assert any("configured owner/chat" in r for r in check(env, cid).reasons)


def test_gate_denies_level2_approval_when_level2_off(env, make_clip):
    cid = make_clip()
    sha = gate.sha256_file(env.store.get_clip(cid)["path"])
    env.store.mark_previewed(cid, sha, 1)
    env.store.approve_clip(cid, "auto:level2", sha)  # the store accepts the label...
    result = check(env, cid)  # ...the gate does not, because level 2 is off in config
    assert not result and any("level 2 is off" in r for r in result.reasons)


def test_gate_level2_needs_config_qa_and_delay(env, make_clip):
    cfg = AutoConfig(level=2, auto_approve={"enabled": True, "min_qa": 90, "delay_minutes": 60})
    low = make_clip(qa=80)
    sha = gate.sha256_file(env.store.get_clip(low)["path"])
    env.store.mark_previewed(low, sha, 1)
    env.store.approve_clip(low, "auto:level2", sha)
    assert any("QA" in r for r in check(env, low, config=cfg).reasons)
    high = make_clip(qa=95)
    sha = gate.sha256_file(env.store.get_clip(high)["path"])
    env.store.mark_previewed(high, sha, 1)
    env.store.approve_clip(high, "auto:level2", sha)
    assert any("delay" in r for r in check(env, high, config=cfg).reasons)
    later = datetime.now(UTC) + timedelta(minutes=61)
    assert check(env, high, config=cfg, now=later)


def test_level2_requires_both_switches():
    assert not AutoConfig(level=2).level2_active
    assert not AutoConfig(auto_approve={"enabled": True}).level2_active
    assert AutoConfig(level=2, auto_approve={"enabled": True}).level2_active
    assert not AutoConfig().level2_active


def test_gate_denies_expired_approval(env, make_clip):
    cid = make_clip(approve=True)
    later = datetime.now(UTC) + timedelta(hours=env.config.post.approval_ttl_hours + 1)
    assert any("expired" in r for r in check(env, cid, now=later).reasons)


def test_gate_denies_raw_cinematic_and_failed_report(env, make_clip):
    assert not check(env, make_clip(approve=True, spoiler_level="raw-cinematic"))
    assert not check(env, make_clip(approve=True, report_status="blocked"))


def test_gate_rules_recheck_missing_hashtag_and_duration(env, make_clip):
    assert any("hashtag" in r for r in check(env, make_clip(approve=True, hashtags=[])).reasons)
    cid = make_clip(approve=True)
    result = check(env, cid, probe_duration=lambda _p: 200.0)
    assert any("max" in r for r in result.reasons)


def test_gate_denies_inactive_or_ended_campaign(env, make_clip):
    cid = make_clip(approve=True)
    side = env.campaigns / "auto" / "test-campaign.yaml"
    side.write_text("streamers: [x]\nactive: false\n", encoding="utf-8")
    assert any("switched off" in r for r in check(env, cid).reasons)
    side.write_text("streamers: [x]\nends_at: 2020-01-01\n", encoding="utf-8")
    assert any("ended" in r for r in check(env, cid).reasons)


def test_gate_denies_unknown_campaign_and_bad_platform(env, make_clip):
    assert not check(env, make_clip(approve=True, campaign_key="no-such-campaign"))
    assert not check(env, make_clip(approve=True), platforms=["myspace"])
    assert not check(env, make_clip(approve=True), platforms=[])


def test_gate_budget_stops_posting(env, make_clip):
    cid = make_clip(approve=True)
    side = env.campaigns / "auto" / "test-campaign.yaml"
    side.write_text("streamers: [x]\nbudget_usd: 1.0\n", encoding="utf-8")
    first = make_clip(approve=True)
    pid = env.store.enqueue_post(first, datetime.now(UTC), ["tiktok"])
    env.store.claim_post(pid)
    env.store.finish_post(pid, request_id="r", results={}, posted_at=datetime.now(UTC),
                          submit_deadline=None)  # fmt: skip
    env.store.add_metric(pid, "tiktok", views=5000)  # $5 > $1 budget
    assert any("budget" in r for r in check(env, cid).reasons)


def test_gate_daily_cap(env, make_clip):
    cfg = AutoConfig(post={"max_per_day": 1})
    first = make_clip(approve=True)
    pid = env.store.enqueue_post(first, datetime.now(UTC), ["tiktok"])
    env.store.claim_post(pid)
    env.store.finish_post(pid, request_id="r", results={}, posted_at=datetime.now(UTC),
                          submit_deadline=None)  # fmt: skip
    assert any("daily cap" in r for r in check(env, make_clip(approve=True), config=cfg).reasons)


def test_gate_fails_closed_on_internal_error(env, make_clip):
    cid = make_clip(approve=True)

    def boom(_p):
        raise RuntimeError("ffprobe exploded")

    result = check(env, cid, probe_duration=boom)
    assert not result and "gate error" in result.reasons[0]


def test_gate_denials_are_audited(env, make_clip):
    check(env, make_clip())
    assert env.store.events("gate_denied")


def test_notifier_has_no_chat_id_parameter():
    import inspect

    from autoclip.auto.notify import TelegramNotifier

    for name in ("send_text", "send_video"):
        assert "chat_id" not in inspect.signature(getattr(TelegramNotifier, name)).parameters


def test_store_is_independent_per_path(tmp_path):
    a, b = Store(tmp_path / "a.db"), Store(tmp_path / "b.db")
    a.set_paused(True)
    assert a.is_paused() and not b.is_paused()
