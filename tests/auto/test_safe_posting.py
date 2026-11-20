"""Safe posting: ramped per-platform caps, spacing, stagger, best-QA-first, expiry, auto-throttle,
the PAUSE file, removal handling, level-2 stays off by default, and the review's fixes."""

from __future__ import annotations

import os
import random
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from autoclip.auto import approval, gate, schedule, throttle
from autoclip.auto.config import AutoConfig
from autoclip.auto.notify import RecordingNotifier
from autoclip.auto.store import parse_iso

NOW = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)  # 09:00 in Copenhagen
KW = {"probe_duration": lambda _p: 30.0}


def cfg(**post):
    base = {"timezone": "UTC", "slots": ["09:00", "22:00"], "start_date": "2026-11-20"}
    return AutoConfig(post=base | post)


def posts_on(env, platform):
    rows = [p for p in env.store.list_posts() if platform in p["platforms"] and p["status"] != "cancelled"]
    return sorted(parse_iso(p["scheduled_for"]) for p in rows)


def test_default_ramp_is_1_2_3_per_platform_per_day(env, make_clip):
    config = cfg()
    assert [config.post.per_platform_daily_caps[i] for i in range(3)] == [1, 2, 3]
    week1, week2, week3 = NOW, NOW + timedelta(days=8), NOW + timedelta(days=15)
    assert [schedule.daily_cap(env.store, config, "tiktok", t) for t in (week1, week2, week3)] == [1, 2, 3]
    assert schedule.daily_cap(env.store, config, "tiktok", NOW + timedelta(days=60)) == 3  # never more


def test_week_one_spreads_a_platform_over_days_with_4h_spacing(env, make_clip):
    config = cfg()
    for _ in range(3):
        make_clip(approve=True)
    schedule.schedule_approved(env.store, config, NOW, random.Random(1))
    for platform in ("tiktok", "youtube", "instagram"):
        times = posts_on(env, platform)
        assert len(times) == 3
        assert len({t.date() for t in times}) == 3  # week 1: one post per platform per day
        assert all(b - a >= timedelta(hours=4) for a, b in zip(times, times[1:], strict=False))


def test_clips_are_staggered_across_platforms(env, make_clip):
    cid = make_clip(approve=True)
    schedule.schedule_approved(env.store, cfg(), NOW, random.Random(3))
    times = sorted(parse_iso(p["scheduled_for"]) for p in env.store.list_posts())
    assert len(times) == 3
    assert times[1] - times[0] >= timedelta(minutes=60) and times[2] - times[1] >= timedelta(minutes=60)
    assert len({tuple(p["platforms"]) for p in env.store.list_posts()}) == 3
    assert env.store.get_clip(cid)["status"] == "approved"


def test_best_qa_goes_first_and_the_rest_wait_or_expire(env, make_clip):
    config = cfg(queue_expiry_hours=30)
    low = make_clip(approve=True, qa=62)
    high = make_clip(approve=True, qa=95)
    third = make_clip(approve=True, qa=70)
    schedule.schedule_approved(env.store, config, NOW, random.Random(2))
    first = {c: min(parse_iso(p["scheduled_for"]) for p in env.store.list_posts() if p["clip_id"] == c)
             for c in (high, third) if any(p["clip_id"] == c for p in env.store.list_posts())}  # fmt: skip
    assert high in first and first[high] <= NOW + timedelta(hours=14)  # best QA posts first
    # a one-post-a-day platform with a 30 h expiry cannot fit three clips: the worst expires
    statuses = {c: env.store.get_clip(c)["status"] for c in (low, high, third)}
    assert statuses[low] == "expired" and statuses[high] == "approved"


def test_stale_unposted_clips_expire(env, make_clip):
    cid = make_clip()
    later = datetime.now(UTC) + timedelta(hours=49)
    assert schedule.expire_stale(env.store, AutoConfig(), later) == 1
    assert env.store.get_clip(cid)["status"] == "expired"


def test_gate_enforces_the_per_platform_cap(env, make_clip):
    config = cfg()
    a, b = make_clip(approve=True), make_clip(approve=True)
    pid = env.store.enqueue_post(a, NOW - timedelta(hours=1), ["tiktok"])
    env.store.claim_post(pid)
    env.store.finish_post(pid, request_id="r", results={}, posted_at=NOW, submit_deadline=None)
    res = gate.check_post_allowed(env.store, b, config=config, platforms=["tiktok"], now=NOW, **KW)
    assert any("tiktok daily cap of 1" in r for r in res.reasons)
    other = gate.check_post_allowed(env.store, b, config=config, platforms=["youtube"], now=NOW, **KW)
    assert other.allowed, other.reasons  # another platform is unaffected


def _post_with_views(env, make_clip, platform, days_ago, views):
    cid = make_clip(approve=True)
    pid = env.store.enqueue_post(cid, NOW - timedelta(days=days_ago), [platform])
    env.store.claim_post(pid)
    env.store.finish_post(pid, request_id="r", results={}, posted_at=NOW - timedelta(days=days_ago),
                          submit_deadline=None)  # fmt: skip
    env.store.add_metric(pid, platform, views=views, fetched_at=NOW)
    return pid


def test_throttle_pauses_a_suppressed_platform_and_halves_the_cap(env, make_clip):
    config = AutoConfig()
    for days, views in ((6, 1000), (5, 900), (4, 1100), (3, 10), (2, 8), (1.5, 5)):
        _post_with_views(env, make_clip, "tiktok", days, views)
    assert throttle.evaluate(env.store, config, NOW) == ["tiktok"]
    until = env.store.platform_pause_until("tiktok")
    assert until and until - NOW == timedelta(hours=48)
    assert env.store.cap_factor("tiktok") == 0.5
    assert any("last-3 average" in e["detail"] for e in env.store.events("throttle"))
    assert throttle.evaluate(env.store, config, NOW) == []  # already paused: no double halving
    blocked = make_clip(approve=True)
    res = gate.check_post_allowed(env.store, blocked, config=config, platforms=["tiktok"], now=NOW, **KW)
    assert any("paused by the auto-throttle" in r for r in res.reasons)


def test_throttle_leaves_healthy_accounts_alone(env, make_clip):
    for days, views in ((6, 1000), (5, 900), (4, 1100), (3, 800), (2, 700), (1.5, 900)):
        _post_with_views(env, make_clip, "youtube", days, views)
    assert throttle.evaluate(env.store, AutoConfig(), NOW) == []


def test_removal_pauses_everything_until_resume(env, make_clip):
    cid = make_clip(approve=True)
    throttle.report_removal(env.store, "instagram", "copyright claim")
    assert env.store.is_paused() and env.store.pause_file.exists()
    res = gate.check_post_allowed(env.store, cid, config=cfg(), platforms=["youtube"], now=NOW, **KW)
    assert not res.allowed and "paused" in res.reasons[0]
    assert env.store.events("removal")
    env.store.set_paused(False, "cli")
    assert not env.store.is_paused()


def test_a_manually_created_pause_file_blocks_posting(env, make_clip):
    cid = make_clip(approve=True)
    env.store.pause_file.write_text("stop", encoding="utf-8")  # e.g. `echo > PAUSE`
    assert not gate.check_post_allowed(env.store, cid, config=cfg(), platforms=["youtube"], now=NOW, **KW)


def test_level2_is_off_by_default_and_does_nothing(env, make_clip):
    cid = make_clip(qa=99)
    env.store.mark_previewed(cid, gate.sha256_file(env.store.get_clip(cid)["path"]), 1)
    assert approval.auto_approve_pending(env.store, AutoConfig()) == 0
    assert env.store.get_clip(cid)["status"] == "pending_approval"
    assert approval.auto_approve_pending(env.store, AutoConfig(level=2)) == 0  # one switch is not enough


def test_level2_needs_both_switches_then_respects_min_qa_and_delay(env, make_clip):
    config = AutoConfig(level=2, auto_approve={"enabled": True, "min_qa": 90, "delay_minutes": 0})
    low, high = make_clip(qa=80), make_clip(qa=95)
    for c in (low, high):
        env.store.mark_previewed(c, gate.sha256_file(env.store.get_clip(c)["path"]), 1)
    assert approval.auto_approve_pending(env.store, config) == 1
    assert env.store.get_clip(high)["approved_by"] == "auto:level2"
    assert env.store.get_clip(low)["status"] == "pending_approval"
    res = gate.check_post_allowed(env.store, high, config=config, platforms=["youtube"], **KW)
    assert res.allowed, res.reasons


def test_failed_post_does_not_requeue_the_clip(env, make_clip):
    from autoclip.auto import poster

    cid = make_clip(approve=True)
    pid = env.store.enqueue_post(cid, NOW, ["youtube"])
    env.store.claim_post(pid)
    env.store.fail_post(pid, "boom")
    poster._retire_clip(env.store, cid, "post_failed")
    assert env.store.get_clip(cid)["status"] == "post_failed"
    assert schedule.schedule_approved(env.store, cfg(), NOW) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific liveness check")
def test_tick_lock_liveness_check_does_not_kill_anything():
    from autoclip.auto.tick import _pid_alive

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert _pid_alive(child.pid) and child.poll() is None  # still running afterwards
        assert not _pid_alive(0)
    finally:
        child.kill()


def test_selection_run_is_confined_and_tool_restricted(env, tmp_path):
    from autoclip.auto import claude_cli

    cmd = claude_cli.build_command(
        "p", model="sonnet", allowed_tools=["Read", "Write"], add_dirs=[],
        max_turns=5, claude_path="claude", disallowed_tools=claude_cli.UNTRUSTED_DISALLOWED,
    )  # fmt: skip
    assert "--add-dir" not in cmd
    banned = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert {"Bash", "Edit", "WebFetch"} <= set(banned)


def test_telegram_group_chat_is_refused(env):
    from autoclip.auto import telegram_bot

    with pytest.raises(RuntimeError, match="private chat"):
        telegram_bot.run_bot(env.store, env.config, token="1:a", chat_id="-100123")


def test_notifier_unused(env):
    assert RecordingNotifier().texts == []
