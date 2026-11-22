"""Metadata-only backfill and atomic throttles: no external services."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import httpx
import pytest
from autoclip.auto import cli, tick, watcher
from autoclip.auto.campaign_meta import AutoCampaign, AutoMeta
from autoclip.stream.campaigns import Campaign
from typer.testing import CliRunner

NOW = datetime(2026, 11, 22, 12, tzinfo=UTC)


def campaign(platform="youtube", key="demo"):
    return AutoCampaign(
        key,
        Campaign(name="Demo"),
        AutoMeta(
            platform=platform,
            streamers=["@exact.handle" if platform == "youtube" else "alice"],
            starts_at=date(2026, 11, 19),
        ),
    )


def vod(id="finished", title="GTA VI playthrough", created="2026-11-19T12:00:00+00:00", **extra):
    return dict(
        id=id,
        title=title,
        created_at=created,
        duration="7h",
        url=f"https://example.test/{id}",
        **extra,
    )


def test_backfill_dry_run_listing_filter_slicing_and_old_sources(env, monkeypatch):
    entries = [
        vod("old", created="2026-11-18T12:00:00+00:00"),
        vod("other", title="Chess"),
        vod(),
        vod("new", created=NOW.isoformat()),
        vod("live", is_live=True),
    ]
    monkeypatch.setattr(watcher, "_youtube_vods", lambda handle, since: entries)
    output = []
    plans = watcher.backfill(env.store, env.config, campaign(), dry_run=True, emit=output.append)
    assert [(p["vod_id"], p["start_s"], p["end_s"]) for p in plans] == [
        (id, a, b)
        for id in ("new", "finished")
        for a, b in ((0, 9000), (9000, 18000), (18000, 25200))
    ]
    assert not env.store.list_jobs()
    assert any("Skipped live stream live" in s for s in output)
    assert "finished | GTA VI playthrough | 2026-11-19T12:00:00+00:00 | 25200s" in output


def test_backfill_enqueue_dedupe_baseline_max_and_settings(env, monkeypatch):
    monkeypatch.setattr(watcher, "_youtube_vods", lambda *a, **k: [vod()])
    env.store.add_job(platform="youtube", campaign_key="demo", vod_id="finished", state="skipped")
    plans = watcher.backfill(env.store, env.config, campaign(), max_slices=2, per_day_hours=4)
    assert len(plans) == 2
    assert env.store.get_meta("backfill:daily_limit:demo") == "4"
    jobs = env.store.list_jobs("queued")
    assert len(jobs) == 2
    assert all(env.store.get_meta(f"backfill:job:{j['id']}") for j in jobs)
    remaining = watcher.backfill(env.store, env.config, campaign())
    assert [(p["start_s"], p["end_s"]) for p in remaining] == [(18000, 25200)]
    # Different boundaries do not redownload already queued intervals.
    assert watcher.backfill(env.store, env.config, campaign(), slice_hours=3) == []


def test_dylan_all_titles_and_cutoff(env, monkeypatch):
    monkeypatch.setattr(watcher, "_youtube_vods", lambda *a, **k: [vod(title="Marathon day 1")])
    assert (
        len(
            watcher.backfill(
                env.store, env.config, campaign(key="dylan-page-marathon"), dry_run=True
            )
        )
        == 3
    )


def test_twitch_game_filter_and_pagination(env, monkeypatch):
    monkeypatch.setattr(watcher.secrets, "get_secret", lambda name: "mock-secret")
    watcher._tokens.clear()
    pages = []

    def handler(request):
        path = request.url.path
        if path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})
        if path.endswith("/users"):
            assert request.url.params["login"] == "alice"
            return httpx.Response(200, json={"data": [{"id": "u"}]})
        if path.endswith("/streams"):
            return httpx.Response(200, json={"data": [{"id": "current"}]})
        assert path.endswith("/videos")
        after = request.url.params.get("after")
        pages.append(after)
        return httpx.Response(
            200,
            json={
                "data": [vod("second", title="Chess")]
                if after
                else [
                    vod(title="Untitled", game_name="Grand Theft Auto VI"),
                    vod("live", stream_id="current"),
                ],
                "pagination": {} if after else {"cursor": "next"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        plans = watcher.backfill(
            env.store, env.config, campaign("twitch"), dry_run=True, client=client
        )
    assert {p["vod_id"] for p in plans} == {"finished"}
    assert pages == [None, "next"]
    watcher._tokens.clear()


def mark_backfill(env, id, hours=2.5):
    job = env.store.add_job(campaign_key="missing", vod_id=id, end_s=hours * 3600)
    env.store.set_meta(f"backfill:job:{job}", "1")
    return job


def test_throttle_priority_per_tick_daily_and_next_day(env):
    first = mark_backfill(env, "first")
    mark_backfill(env, "second")
    recent = env.store.add_job(campaign_key="missing", vod_id="recent")
    assert tick.claim_tick_job(env.store, 0, NOW)["id"] == recent
    assert tick.claim_tick_job(env.store, 0, NOW)["id"] == first
    assert tick.claim_tick_job(env.store, 1, NOW) is None
    assert tick.claim_tick_job(env.store, 0, NOW) is not None
    mark_backfill(env, "third")
    assert tick.claim_tick_job(env.store, 0, NOW) is None  # 5 + 2.5 exceeds 6 h
    assert tick.claim_tick_job(env.store, 0, datetime(2026, 11, 23, tzinfo=UTC))


def test_custom_throttle_and_daily_override(env, monkeypatch):
    from autoclip.auto import campaign_meta

    c = campaign()
    c.meta.backfill.max_slices_per_tick = 2
    c.meta.backfill.max_hours_per_day = 8
    monkeypatch.setattr(campaign_meta, "load_auto_campaign", lambda key: c)
    mark_backfill(env, "first")
    mark_backfill(env, "second")
    assert tick.claim_tick_job(env.store, 1, NOW)
    assert tick.claim_tick_job(env.store, 2, NOW) is None
    env.store.set_meta("backfill:daily_limit:missing", "3")
    assert tick.claim_tick_job(env.store, 0, NOW) is None


def test_cli_dry_run_no_persistent_store(env, monkeypatch):
    monkeypatch.setattr(watcher, "_youtube_vods", lambda *a, **k: [vod()])
    from autoclip.auto import campaign_meta

    monkeypatch.setattr(campaign_meta, "load_auto_campaign", lambda key: campaign())
    monkeypatch.setattr(cli, "Store", lambda: pytest.fail("dry-run created store"))
    result = CliRunner().invoke(cli.app, ["backfill", "--campaign", "demo", "--dry-run"])
    assert result.exit_code == 0, result.exception
    assert "Would enqueue 3 slices" in result.stdout


def test_backfill_disk_guard(env, monkeypatch):
    monkeypatch.setattr(watcher, "disk_ok", lambda config: (False, "full"))
    monkeypatch.setattr(
        watcher, "_youtube_vods", lambda *a, **k: pytest.fail("discovery on full disk")
    )
    assert watcher.backfill(env.store, env.config, campaign()) == []


def test_range_subtraction_preserves_unprocessed_tail():
    known = [{"platform": "youtube", "vod_id": "v", "start_s": 0, "end_s": 21600, "state": "done"}]
    assert list(watcher.backfill_ranges(42898, 9000, known, "youtube", "v")) == [
        (21600, 30600),
        (30600, 39600),
        (39600, 42898),
    ]


def test_runner_youtube_command_and_skip_done(env):
    from autoclip.auto import runner

    id = env.store.add_job(
        campaign_key="dylan-page-marathon",
        platform="youtube",
        vod_id="yt-id",
        url="https://www.youtube.com/watch?v=yt-id",
        start_s=9000,
        end_s=18000,
    )
    job = env.store.claim_next_job()
    command = runner.stream_command(job, ["--prepare-only"])
    assert command[command.index("--start") + 1] == "2:30:00"
    assert command[command.index("--end") + 1] == "5:00:00"
    fake = lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="Stream skipped: still live", stderr=""
    )
    assert runner.process_job(env.store, env.config, job, runner=fake) == 0
    assert env.store.get_job(id)["state"] == "done"


def test_all_gate_failures_are_done_not_retried(env, monkeypatch):
    import json

    from autoclip import paths
    from autoclip.auto import runner

    id = env.store.add_job(campaign_key="test-campaign", vod_id="rejected")
    job = env.store.claim_next_job()
    out = paths.exports_dir() / "abcdef"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps([{"status": "rejected", "title": "No cut"}]))
    calls = iter(
        [
            SimpleNamespace(returncode=0, stdout="Job id: abcdef", stderr=""),
            SimpleNamespace(returncode=1, stdout="No usable clips", stderr=""),
        ]
    )
    assert (
        runner.process_job(
            env.store,
            env.config,
            job,
            runner=lambda *a, **k: next(calls),
            select=lambda *a: env.tmp / "highlights.json",
        )
        == 0
    )
    assert env.store.get_job(id)["state"] == "done"


def test_youtube_backfill_uses_publication_date_not_stream_start(monkeypatch):
    import yt_dlp

    class FakeYDL:
        def __init__(self, options):
            assert options["skip_download"] is True
            assert options["proxy"] == ""
            assert "playlistend" not in options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            assert download is False
            return {
                "entries": [
                    {
                        "id": "day1",
                        "title": "DAY 1",
                        "live_status": "was_live",
                        "timestamp": datetime(2026, 11, 19, 11, tzinfo=UTC).timestamp(),
                        "release_timestamp": datetime(2026, 11, 18, 23, tzinfo=UTC).timestamp(),
                        "duration": 42895,
                    }
                ]
            }

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    result = watcher._youtube_vods("@dylan.page.", since=date(2026, 11, 19))
    assert len(result) == 1
    assert result[0]["created_at"].startswith("2026-11-19")
