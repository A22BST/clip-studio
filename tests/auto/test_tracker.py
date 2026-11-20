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
