"""The acceptance test with mocks: a fake new VOD -> job -> clips -> approval -> /pause blocks
the queued post -> /resume -> posting call -> tracker row. No network, no ffmpeg, no claude."""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from autoclip import paths
from autoclip.auto import discord_bot, diskguard, runner, submit_log, tick, tracker, watcher
from autoclip.auto.notify import RecordingNotifier
from autoclip.auto.store import parse_iso

JOB = "e2e0001"
OWNER = "555"


class FakePublisher:
    """Each upload gets its own request id and only reports on the platforms it was sent to."""

    def __init__(self):
        self.uploads = []
        self.by_request = {}

    def upload(self, **kw):
        from autoclip.auto.uploadpost import UploadResult

        self.uploads.append(kw)
        rid = f"req-{len(self.uploads)}"
        self.by_request[rid] = list(kw["platforms"])
        return UploadResult(rid, [])

    def status(self, request_id):
        return {
            "status": "completed",
            "results": [
                {"platform": p, "success": True, "post_url": f"https://{p}.test/clip1"}
                for p in self.by_request[request_id]
            ],
        }

    def history(self, request_id):
        return []

    def post_analytics(self, request_id):
        from autoclip.auto.uploadpost import Metrics

        return {p: Metrics(views=2500, likes=100, comments=5, shares=9) for p in self.by_request[request_id]}


def twitch_client(now):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if path.endswith("/users"):
            return httpx.Response(200, json={"data": [{"id": "42"}]})
        if path.endswith("/streams"):
            return httpx.Response(200, json={"data": []})
        vod = {
            "id": "98765", "title": "GTA 6 day 3", "url": "https://www.twitch.tv/videos/98765",
            "created_at": (now - timedelta(hours=2)).isoformat(), "duration": "2h10m0s",
        }  # fmt: skip
        return httpx.Response(200, json={"data": [vod]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def fake_pipeline(env):
    """Stands in for `clip stream` (prepare/render) and the headless /clip selection."""
    exports = paths.exports_dir() / JOB
    work = paths.job_work_dir(JOB)

    def run(cmd, **kw):
        if "--prepare-only" in cmd:
            work.mkdir(parents=True, exist_ok=True)
            (work / "candidates.json").write_text(
                json.dumps({"candidates": [{"first_word": 0, "last_word": 500}]}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0, f"(Job id: {JOB})", "")
        exports.mkdir(parents=True, exist_ok=True)
        good = exports / "he-did-not-expect-this.mp4"
        good.write_bytes(b"rendered clip bytes")
        report = [
            {"title": "He did NOT expect this", "hook": "Wait for it", "caption": "Insane moment",
             "hashtags": ["GTA6", "KreekCraft"], "qa_score": 88, "status": "exported",
             "spoiler_level": "none", "layout_used": "facecam", "path": str(good),
             "start_s": 10, "end_s": 40, "violations": []},
            {"title": "Cutscene", "status": "rejected", "spoiler_level": "raw-cinematic",
             "qa_score": 0, "path": "", "violations": [], "start_s": 0, "end_s": 0},
        ]  # fmt: skip
        (exports / "report.json").write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def select(job_id, config):
        out = work / "highlights.json"
        out.write_text(json.dumps({"clips": [{"title": "He did NOT expect this", "hook": "x",
                                              "start_word_index": 5, "end_word_index": 200,
                                              "score": 90}]}), encoding="utf-8")  # fmt: skip
        return out

    return lambda store, config, job: runner.process_job(
        store, config, job, runner=run, select=select
    )


def test_vod_to_post_to_tracker_with_pause(env, monkeypatch):
    monkeypatch.setenv("DISCORD_OWNER_ID", OWNER)
    monkeypatch.setattr(diskguard, "free_gb", lambda p: 100)
    watcher._tokens.clear()
    monkeypatch.setenv("TWITCH_CLIENT_ID", "x")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "x")
    env.config.watch.baseline_on_first_run = False
    now = datetime.now(UTC)
    notifier, publisher = RecordingNotifier(), FakePublisher()
    kw = {"probe_duration": lambda p: 30.0}

    # 1. a new VOD appears: the tick queues it, runs the job, and previews the clip
    summary = tick.tick(
        env.store, env.config, notifier, client=publisher, now=now, gate_kwargs=kw,
        scan=lambda store, config, now=None: watcher.scan(store, config, now=now, client=twitch_client(now)),
        process=fake_pipeline(env),
    )  # fmt: skip
    assert summary["new_jobs"] == 1 and summary["jobs_run"] == 1 and summary["clips"] == 1
    clips = env.store.list_clips()
    assert len(clips) == 1 and clips[0]["status"] == "pending_approval"  # the cutscene was dropped
    assert len(notifier.videos) == 1  # preview sent with Approve/Reject/Edit buttons
    ids = [b.callback_data for row in notifier.videos[0][2] for b in row]
    token = clips[0]["previewed_sha256"][:12]
    assert ids == [f"a:{clips[0]['id']}:{token}", f"r:{clips[0]['id']}", f"e:{clips[0]['id']}"]
    assert publisher.uploads == []  # nothing posts before a human decides

    # 2. Ahmad taps Approve (Discord owner)
    cid = clips[0]["id"]
    reply, _ = discord_bot.handle_button(env.store, env.config, f"a:{cid}", OWNER)
    assert reply == "Approved."

    # 3. /pause while the posts are queued and due: no upload may happen
    env.store.set_paused(True, "test")
    tick.post_cycle(env.store, env.config, notifier, publisher, now=now, gate_kwargs=kw)
    posts = env.store.list_posts()
    assert len(posts) == 3 and all(len(p["platforms"]) == 1 for p in posts)  # one row per platform
    times = sorted(parse_iso(p["scheduled_for"]) for p in posts)
    assert times[1] - times[0] >= timedelta(minutes=60)  # platforms are staggered 1-2 h apart
    assert times[2] - times[1] >= timedelta(minutes=60)
    # The posting window can stagger later platforms into the next day.
    far = times[-1] + timedelta(seconds=1)  # every scheduled post is due
    tick.post_cycle(env.store, env.config, notifier, publisher, now=far, gate_kwargs=kw)
    assert publisher.uploads == [] and {p["status"] for p in env.store.list_posts()} == {"queued"}
    assert env.store.pause_file.exists()  # the PAUSE flag file is the kill switch

    # 4. /resume: each platform posts once; the chat gets the URLs and the submit-now reminder
    env.store.set_paused(False, "test")
    assert not env.store.pause_file.exists()
    tick.post_cycle(env.store, env.config, notifier, publisher, now=far, gate_kwargs=kw)
    reasons = [e["detail"] for e in env.store.events("gate_denied")]
    assert len(publisher.uploads) == 3, ([(p["status"], p["error"]) for p in env.store.list_posts()], reasons)
    assert sorted(u["platforms"][0] for u in publisher.uploads) == ["instagram", "tiktok", "youtube"]
    assert {p["status"] for p in env.store.list_posts()} == {"posted"}
    text = [t for t, _ in notifier.texts if "submit to Content Rewards now" in t]
    assert len(text) == 3 and any("youtube.test/clip1" in t for t in text)
    assert env.store.get_clip(cid)["status"] == "posted"
    submit_rows = list(csv.DictReader(open(submit_log.csv_path(), encoding="utf-8")))
    assert {r["platform"] for r in submit_rows} == {"tiktok", "youtube", "instagram"}  # posted_to_submit.csv

    # 5. a second cycle never uploads the same clip again
    tick.post_cycle(env.store, env.config, notifier, publisher, now=far, gate_kwargs=kw)
    assert len(publisher.uploads) == 3

    # 6. views are pulled and a tracker row exists
    tracker.pull_views(env.store, env.config, publisher, now=far + timedelta(days=1))
    rows = list(csv.DictReader(open(env.config.tracker_csv(), encoding="utf-8")))
    assert {r["platform"] for r in rows} == {"tiktok", "youtube", "instagram"}
    assert all(int(r["views"]) == 2500 for r in rows), rows
    assert float(rows[0]["estimated_usd"]) == pytest.approx(2.5)  # 2500 views at $1.00 per 1k


def test_an_unapproved_clip_never_posts_even_if_queued_by_force(env, make_clip):
    cid = make_clip()  # pending_approval
    with pytest.raises(Exception):
        env.store.enqueue_post(cid, datetime.now(UTC), ["youtube"])
    assert env.store.list_posts() == []


@pytest.mark.parametrize("held", [False, True])
def test_keyless_tick_vod_to_outbox(env, monkeypatch, caplog, held):
    from autoclip.auto import approval, cli, outbox, poster, schedule, secrets, submit

    # Isolate credential presence from both the process and the Windows registry.
    monkeypatch.setattr(secrets, "secret_is_set", lambda name: name.startswith("TWITCH_"))
    monkeypatch.setenv("TWITCH_CLIENT_ID", "x")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "x")
    monkeypatch.setattr(diskguard, "free_gb", lambda p: 100)
    watcher._tokens.clear()
    env.config.watch.baseline_on_first_run = False
    assert env.config.selection.backend == "chain"
    now = datetime.now(UTC)

    def forbidden(*args, **kwargs):
        pytest.fail("keyless tick entered the posting workflow")

    for module, name in (
        (approval, "send_pending_previews"), (approval, "auto_approve_pending"),
        (schedule, "expire_stale"), (poster, "schedule_approved"),
        (poster, "post_due"), (poster.gate, "check_post_allowed"),
        (submit, "send_reminders"), (poster, "UploadPostClient"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    process = fake_pipeline(env)

    def render(store, config, job):
        count = process(store, config, job)
        work = paths.job_work_dir(JOB)
        (work / "transcript.json").write_text(json.dumps({"words": [
            {"start": 12, "end": 13, "text": "naked" if held else "hello"}
        ]}))
        # The outbox must select the pipeline's finished SFX variant.
        (paths.exports_dir() / JOB / "he-did-not-expect-this_sfx.mp4").write_bytes(b"sfx clip")
        return count

    calls = []
    after_render = outbox.after_render

    def export(*args, **kwargs):
        calls.append(args[2]["id"])
        return after_render(*args, **kwargs)

    monkeypatch.setattr(outbox, "after_render", export)
    with caplog.at_level("INFO"):
        summary = tick.tick(
            env.store, env.config, cli._notifier(env.config), now=now,
            scan=lambda store, config, now=None: watcher.scan(
                store, config, now=now, client=twitch_client(now)),
            process=render,
        )
    assert summary["new_jobs"] == summary["jobs_run"] == summary["clips"] == 1
    assert len(calls) == 1
    assert summary["outbox_copied"] == int(not held)
    assert summary["outbox_held"] == int(held)
    assert poster.OUTBOX_ONLY in caplog.text
    assert summary["publisher"] == poster.OUTBOX_ONLY
    assert env.store.list_posts() == []
    ledger = json.loads((outbox.outbox_dir(env.config) / "outbox.json").read_text())
    assert len(ledger) == 1
    from pathlib import Path
    assert Path(next(iter(ledger.values()))["path"]).read_bytes() == b"sfx clip"


def test_publisher_can_be_added_after_outbox_only(env, make_clip, monkeypatch):
    from autoclip.auto import poster, secrets

    make_clip(approve=True)
    ready = False
    monkeypatch.setattr(secrets, "secret_is_set", lambda name: ready and name == secrets.UPLOAD_POST_API_KEY)
    notifier = RecordingNotifier()
    now = datetime.now(UTC)
    result = tick.post_cycle(env.store, env.config, notifier, now=now)
    assert result["scheduled"] == 0
    assert env.store.list_posts() == []
    assert poster.post_due(env.store, env.config, notifier, now=now) == []
    ready = True
    publisher = FakePublisher()
    result = tick.post_cycle(env.store, env.config, notifier, publisher, now=now)
    assert result["scheduled"] == 3
    assert len(env.store.list_posts()) == 3
