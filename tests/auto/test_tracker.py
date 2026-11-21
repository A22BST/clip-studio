"""CSV rebuilding and per-platform analytics persistence."""

import csv
from datetime import UTC, datetime, timedelta

from autoclip.auto.tracker import FIELDS, append_post_rows, pull_views
from autoclip.auto.uploadpost import Metrics


def posted(env, make_clip, when):
    cid = make_clip(approve=True)
    pid = env.store.enqueue_post(cid, when, ["tiktok", "youtube"])
    env.store.claim_post(pid)
    env.store.finish_post(
        pid,
        request_id=str(pid),
        results={"tiktok": {"url": "https://post.test/1"}},
        posted_at=when,
        submit_deadline=when + timedelta(minutes=30),
    )
    return pid


def test_csv_rows_metrics_and_estimated_usd(env, make_clip, monkeypatch):
    now = datetime.now(UTC)
    env.config.tracker.csv_path = str(env.tmp / "tracker.csv")
    pid = posted(env, make_clip, now - timedelta(days=1))
    old = posted(env, make_clip, now - timedelta(days=46))
    calls = []

    class Client:
        def post_analytics(self, request_id):
            calls.append(request_id)
            return {"tiktok": Metrics(2500, 20, 3, 4), "youtube": Metrics(1000)}

    pull_views(env.store, env.config, Client())
    assert calls == [str(pid)]
    assert not env.store.latest_metrics(old)
    assert env.store.latest_metrics(pid)["tiktok"]["views"] == 2500
    with env.config.tracker_csv().open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert reader.fieldnames == FIELDS
    assert len(rows) == 4
    assert rows[0]["estimated_usd"] == "2.5"
    assert rows[0]["url"] == "https://post.test/1"
    assert rows[0]["likes"] == "20"
    assert rows[0]["last_checked"]
    env.store.mark_submitted(pid)
    append_post_rows(env.store, env.config)
    append_post_rows(env.store, env.config)
    with env.config.tracker_csv().open(encoding="utf-8", newline="") as handle:
        updated = list(csv.DictReader(handle))
    assert len(updated) == 4
    assert updated[0]["submitted_at"]


def test_empty_csv_has_header(env):
    env.config.tracker.csv_path = str(env.tmp / "nested/tracker.csv")
    append_post_rows(env.store, env.config)
    assert env.config.tracker_csv().read_text().strip() == ",".join(FIELDS)


def test_existing_database_migration_is_idempotent_and_preserves_rows(env, make_clip):
    import sqlite3

    from autoclip.auto.store import Store

    cid = make_clip()
    with sqlite3.connect(env.store.path) as con:
        con.execute("ALTER TABLE clips DROP COLUMN provider")
        con.execute("ALTER TABLE clips DROP COLUMN model")
    migrated = Store(env.store.path)
    assert migrated.get_clip(cid)["provider"] == ""
    assert migrated.get_clip(cid)["model"] == ""
    assert Store(env.store.path).get_clip(cid)["title"] == env.store.get_clip(cid)["title"]


def test_selection_metadata_copied_on_registration(env, make_clip):
    import json

    from autoclip import paths

    # make_clip creates the row immediately; create another using its job and fields.
    original = env.store.get_clip(make_clip())
    env.store.update_job(original["job_id"], autoclip_job_id="selection-job")
    folder = paths.job_work_dir("selection-job")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "selection_meta.json").write_text(
        json.dumps({"provider": "free-provider", "model": "free-model"}), encoding="utf-8"
    )
    cid = env.store.add_clip(job_id=original["job_id"], campaign_key="test-campaign",
                             title="Selected", path=original["path"])
    clip = env.store.get_clip(cid)
    assert clip["provider"] == "free-provider" and clip["model"] == "free-model"


def test_tracker_includes_provider_and_model(env, make_clip):
    now = datetime.now(UTC)
    pid = posted(env, make_clip, now)
    env.store.update_clip(env.store.get_post(pid)["clip_id"], provider="free", model="m")
    append_post_rows(env.store, env.config)
    with env.config.tracker_csv().open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert all(r["provider"] == "free" and r["model"] == "m" for r in rows)
