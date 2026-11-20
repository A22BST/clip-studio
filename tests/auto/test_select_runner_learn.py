"""3b headless selection, the job runner and 3e weekly learning, with every subprocess faked."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from autoclip import paths
from autoclip.auto import learn, runner, select
from autoclip.auto.notify import RecordingNotifier

JOB = "abc123"


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


@pytest.fixture
def work(env):
    folder = paths.job_work_dir(JOB)
    folder.mkdir(parents=True)
    (folder / "candidates.json").write_text(
        json.dumps({"candidates": [{"first_word": 100, "last_word": 400}]}), encoding="utf-8"
    )
    return folder


def highlights(start, end):
    return json.dumps(
        {"clips": [{
            "start_word_index": start, "end_word_index": end, "title": "A clip", "hook": "Wow",
            "caption": "c", "hashtags": ["GTA6"], "score": 80, "spoiler_level": "none",
            "layout": "facecam",
        }]}
    )  # fmt: skip


def test_selection_runs_claude_headless_and_validates(env, work):
    seen = {}

    def fake(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw["env"]
        (work / "highlights.json").write_text(highlights(120, 300), encoding="utf-8")
        return done("ok")

    out = select.run_selection(JOB, env.config, runner=fake, cwd=Path.cwd())
    assert out == work / "highlights.json"
    cmd = seen["cmd"]
    assert cmd[1] == "-p" and cmd[2].startswith(f"/clip {JOB}")
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert "Do NOT run `clip stream`" in cmd[2]
    assert "ANTHROPIC_API_KEY" not in seen["env"]


def test_selection_retries_with_the_error_then_succeeds(env, work):
    prompts = []

    def fake(cmd, **kw):
        prompts.append(cmd[2])
        start, end = (9000, 9100) if len(prompts) == 1 else (120, 300)  # first is out of range
        (work / "highlights.json").write_text(highlights(start, end), encoding="utf-8")
        return done()

    select.run_selection(JOB, env.config, runner=fake, cwd=Path.cwd())
    assert len(prompts) == 2 and "previous highlights.json was invalid" in prompts[1]


def test_selection_gives_up_after_max_attempts(env, work):
    calls = []

    def fake(cmd, **kw):
        calls.append(1)
        return done("nothing written", 1)

    with pytest.raises(select.SelectionError):
        select.run_selection(JOB, env.config, runner=fake, cwd=Path.cwd())
    assert len(calls) == env.config.selection.max_attempts


def test_selection_reuses_a_valid_existing_file(env, work):
    (work / "highlights.json").write_text(highlights(120, 300), encoding="utf-8")
    select.run_selection(JOB, env.config, runner=lambda *a, **k: pytest.fail("no call"))


def make_report(env, entries):
    folder = paths.exports_dir() / JOB
    folder.mkdir(parents=True, exist_ok=True)
    for e in entries:
        if e.get("path"):
            Path(e["path"]).write_bytes(b"mp4")
    (folder / "report.json").write_text(json.dumps(entries), encoding="utf-8")


def test_process_job_end_to_end_with_fakes(env, work):
    jid = env.store.add_job(campaign_key="test-campaign", vod_id="9", url="https://twitch.tv/videos/9")
    job = env.store.claim_next_job()
    folder = paths.exports_dir() / JOB
    entry = lambda n, status, path="": dict(  # noqa: E731
        title=n, hook="h", caption="cap", hashtags=["GTA6"], qa_score=88, status=status,
        spoiler_level="none", layout_used="facecam", path=path, start_s=0, end_s=30, violations=[],
    )  # fmt: skip
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "--prepare-only" in cmd:
            return done(f"Candidates\n(Job id: {JOB})\n")
        make_report(env, [entry("one", "exported", str(folder / "one.mp4")),
                          entry("two", "blocked"),
                          entry("three", "exported", str(folder / "three.mp4"))])  # fmt: skip
        return done()

    def fake_select(job_id, config):
        (work / "highlights.json").write_text(highlights(120, 300), encoding="utf-8")
        return work / "highlights.json"

    # candidates.json only exists after prepare in real life; the fixture created it already
    added = runner.process_job(env.store, env.config, job, runner=fake_run, select=fake_select)
    assert added == 2
    assert env.store.get_job(jid)["state"] == "done"
    clips = env.store.list_clips()
    assert {c["status"] for c in clips} == {"pending_approval"}
    assert sorted(c["title"] for c in clips) == ["one", "three"]
    assert all("--campaign" in c and "test-campaign" in c for c in calls)
    # idempotent: ingesting again adds nothing
    assert runner.ingest_report(env.store, env.store.get_job(jid), JOB, folder) == 0


def test_process_job_failure_retries_then_gives_up(env):
    env.store.add_job(campaign_key="test-campaign", vod_id="7")
    boom = lambda cmd, **kw: done("nope", 3)  # noqa: E731
    job = env.store.claim_next_job()
    assert runner.process_job(env.store, env.config, job, runner=boom) == 0
    assert env.store.get_job(job["id"])["state"] == "queued"  # attempt 1 of 2: retry
    job = env.store.claim_next_job()
    runner.process_job(env.store, env.config, job, runner=boom)
    assert env.store.get_job(job["id"])["state"] == "failed"
    assert env.store.events("job_error")


def test_trimmed_slice_command_uses_start_end():
    cmd = runner.stream_command(
        {"url": "u", "vod_id": "1", "campaign_key": "k", "start_s": 10800, "end_s": 21600}, []
    )
    assert cmd[cmd.index("--start") + 1] == "3:00:00" and cmd[cmd.index("--end") + 1] == "6:00:00"


def test_cleanup_waits_for_pending_clips(env, make_clip):
    cid = make_clip()
    job = env.store.get_clip(cid)["job_id"]
    env.store.update_job(job, state="done")
    folder = runner.source_folder(env.store.get_job(job))
    folder.mkdir(parents=True)
    (folder / "vod.mp4").write_bytes(b"x" * 10)
    assert runner.cleanup_sources(env.store, env.config) == 0 and (folder / "vod.mp4").exists()
    env.store.set_clip_status(cid, "rejected")
    assert runner.cleanup_sources(env.store, env.config) == 10 and not (folder / "vod.mp4").exists()


def test_weekly_report_sent_and_rules_saved(env, make_clip, tmp_path):
    text = "## WHAT_WORKS\n- short hooks win\n\n## REPORT\n3 clips posted, 12k views, ~$12."
    n = RecordingNotifier()
    works = tmp_path / "what_works.md"
    report = learn.run_weekly(
        env.store, env.config, n, runner=lambda cmd, **kw: done(text), works_path=works
    )
    assert "12k views" in report and "short hooks win" in works.read_text()
    assert n.texts and n.texts[0][0].startswith("Weekly report")


def test_weekly_report_survives_a_dead_model(env, tmp_path):
    n = RecordingNotifier()
    report = learn.run_weekly(
        env.store, env.config, n, runner=lambda cmd, **kw: done("", 1), works_path=tmp_path / "w.md"
    )
    assert "no report" in report and n.texts
