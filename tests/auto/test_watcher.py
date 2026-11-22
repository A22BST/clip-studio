from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from autoclip.auto import diskguard, watcher
from autoclip.auto.campaign_meta import load_all_auto_campaigns
from autoclip.auto.config import AutoConfig
from autoclip.auto.store import Store

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


@pytest.fixture
def env(tmp_path, monkeypatch):
    directory = tmp_path / "campaigns"
    (directory / "auto").mkdir(parents=True)
    (directory / "demo.yaml").write_text("name: Demo\n", encoding="utf-8")
    sidecar = directory / "auto" / "demo.yaml"
    sidecar.write_text("streamers: [alice]\n", encoding="utf-8")
    monkeypatch.setenv("CLIPSTUDIO_CAMPAIGNS_DIR", str(directory))
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path))
    monkeypatch.setattr(watcher.secrets, "get_secret", lambda name: "test-credential")
    monkeypatch.setattr(diskguard, "free_gb", lambda path: 100)
    watcher._tokens.clear()
    yield SimpleNamespace(
        store=Store(tmp_path / "auto.db"),
        config=AutoConfig(watch={"baseline_on_first_run": False}),
        sidecar=sidecar,
    )
    watcher._tokens.clear()


def vod(vod_id="v1", duration="1h", created=None):
    return {
        "id": vod_id,
        "title": "Archive",
        "created_at": (created or NOW).isoformat(),
        "duration": duration,
        "url": f"https://www.twitch.tv/videos/{vod_id}",
    }


def twitch(vods=None, live=False, broken=None, unauthorized=0):
    requests = []
    state = {"unauthorized": unauthorized, "tokens": 0}

    def handler(request):
        requests.append(request)
        if request.url.path == "/oauth2/token":
            state["tokens"] += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"token-{state['tokens']}",
                    "expires_in": 3600,
                },
            )
        if state["unauthorized"]:
            state["unauthorized"] -= 1
            return httpx.Response(401)
        if request.url.path.endswith("/users"):
            login = request.url.params["login"]
            if login == broken:
                raise httpx.ConnectError("test connection failure", request=request)
            return httpx.Response(200, json={"data": [{"id": login}]})
        if request.url.path.endswith("/streams"):
            return httpx.Response(200, json={"data": [{"id": "live"}] if live else []})
        assert request.url.path.endswith("/videos")
        assert request.url.params["type"] == "archive"
        assert request.url.params["first"] == "5"
        return httpx.Response(200, json={"data": vods if vods is not None else [vod()]})

    return httpx.Client(transport=httpx.MockTransport(handler)), requests, state


def test_new_vod_and_duplicate(env):
    with twitch()[0] as client:
        ids = watcher.scan(env.store, env.config, now=NOW, client=client)
        assert len(ids) == 1
        job = env.store.get_job(ids[0])
        assert job["state"] == "queued"
        assert job["campaign_key"] == "demo"
        assert job["streamer"] == "alice"
        assert (job["start_s"], job["end_s"]) == (0, 0)
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []
        assert len(env.store.list_jobs()) == 1


def test_baseline_marks_even_old_and_live_vods_seen(env):
    env.config.watch.baseline_on_first_run = True
    with twitch([vod(created=NOW - timedelta(days=10))], live=True)[0] as client:
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []
        assert env.store.get_meta("watch_baseline_done") == "1"
        assert len(env.store.list_jobs("skipped")) == 1
    with twitch()[0] as client:
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []


@pytest.mark.parametrize("live,age", [(True, 0), (False, 49)])
def test_live_or_old_vod_skipped(env, live, age):
    with twitch([vod(created=NOW - timedelta(hours=age))], live=live)[0] as client:
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []
        assert env.store.list_jobs() == []


@pytest.mark.parametrize(
    "duration,limit,expected",
    [
        ("7h", 2, [(0, 10800), (10800, 21600)]),
        ("7h", 3, [(0, 10800), (10800, 21600), (21600, 25200)]),
        ("3h", 2, [(0, 0)]),
    ],
)
def test_slices(env, duration, limit, expected):
    env.config.watch.slice_hours = 3
    env.config.watch.max_slices_per_vod = limit
    with twitch([vod(duration=duration)])[0] as client:
        ids = watcher.scan(env.store, env.config, now=NOW, client=client)
        assert len(ids) == len(expected)
        assert [(j["start_s"], j["end_s"]) for j in env.store.list_jobs()] == expected
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []


@pytest.mark.parametrize(
    "meta",
    [
        {"active": False},
        {"ends_at": "2026-11-19"},
        {"platform": "unsupported"},
    ],
)
def test_ineligible_campaign_never_calls_twitch(env, meta):
    env.sidecar.write_text(yaml.safe_dump({"streamers": ["alice"], **meta}), encoding="utf-8")
    with twitch()[0] as client:
        client.get = lambda *args, **kwargs: pytest.fail("unexpected network call")
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []


def test_network_error_does_not_stop_other_streamer(env, caplog):
    env.sidecar.write_text("streamers: [broken, alice]\n", encoding="utf-8")
    with twitch(broken="broken")[0] as client:
        assert len(watcher.scan(env.store, env.config, now=NOW, client=client)) == 1
    assert "broken" in caplog.text
    assert "test-credential" not in caplog.text


def test_failed_baseline_is_retried(env):
    env.config.watch.baseline_on_first_run = True
    env.sidecar.write_text("streamers: [broken, alice]\n", encoding="utf-8")
    with twitch(broken="broken")[0] as client:
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []
    assert not env.store.get_meta("watch_baseline_done")
    assert len(env.store.list_jobs("skipped")) == 1


def test_low_disk_skips_scan(env, monkeypatch):
    monkeypatch.setattr(diskguard, "free_gb", lambda path: 1)
    client, requests, _ = twitch()
    with client:
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []
    assert requests == []
    assert not env.store.get_meta("watch_baseline_done")


def test_refresh_once_and_cache(env):
    client, requests, state = twitch(unauthorized=1)
    with client:
        assert len(watcher.scan(env.store, env.config, now=NOW, client=client)) == 1
        watcher.scan(env.store, env.config, now=NOW, client=client)
    assert state["tokens"] == 2
    assert [r.headers["authorization"] for r in requests if r.url.path.endswith("/users")][:2] == [
        "Bearer token-1",
        "Bearer token-2",
    ]


def test_repeated_401_stops_after_one_refresh(env):
    client, requests, state = twitch(unauthorized=10)
    with client:
        assert watcher.scan(env.store, env.config, now=NOW, client=client) == []
    assert state["tokens"] == 2
    assert len(requests) == 4


def test_injected_campaigns_and_client_remain_usable(env):
    campaigns = load_all_auto_campaigns()
    with twitch()[0] as client:
        assert len(watcher.scan(env.store, env.config, campaigns, NOW, client)) == 1
        assert not client.is_closed


@pytest.mark.parametrize("value,seconds", [("3h12m5s", 11525), ("5s", 5), ("2m", 120)])
def test_parse_duration(value, seconds):
    assert watcher.parse_duration(value) == seconds


@pytest.mark.parametrize("value", ["", "invalid", "3hgarbage", "-1s"])
def test_bad_duration(value):
    with pytest.raises(ValueError):
        watcher.parse_duration(value)


def test_diskguard_missing_root_and_error(tmp_path, monkeypatch):
    assert diskguard.free_gb(tmp_path / "not-created") >= 0
    monkeypatch.setattr(diskguard.paths, "root", lambda: tmp_path)

    def fail(path):
        raise OSError("unavailable")

    monkeypatch.setattr(diskguard, "free_gb", fail)
    assert diskguard.disk_ok(AutoConfig())[0] is False


def test_diskguard_checks_autoclip_root(env, monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr(diskguard, "free_gb", lambda path: observed.append(path) or 10)
    assert diskguard.disk_ok(env.config) == (True, "")
    assert observed == [Path(tmp_path).resolve()]


def youtube_env(env):
    env.sidecar.write_text(
        'streamers: ["@DylanPage"]\nplatform: youtube\nstarts_at: 2026-11-19\n',
        encoding="utf-8",
    )


def test_youtube_metadata_only(monkeypatch):
    import yt_dlp

    class FakeYDL:
        def __init__(self, options):
            assert options["skip_download"] is True
            assert options["playlistend"] == 5

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            assert url == "https://www.youtube.com/@DylanPage/streams"
            assert download is False
            base = {
                "id": "yt1",
                "title": "Marathon",
                "live_status": "was_live",
                "release_timestamp": NOW.timestamp(),
                "duration": 3600,
            }
            return {
                "entries": [
                    base,
                    {**base, "live_status": "is_upcoming"},
                    {**base, "duration": None},
                    {**base, "release_timestamp": None},
                ]
            }

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    result = watcher._youtube_vods("@DylanPage")
    assert len(result) == 1
    assert result[0]["url"] == "https://www.youtube.com/watch?v=yt1"
    assert result[0]["created_at"] == NOW.isoformat()
    assert result[0]["duration"] == "3600s"
    with pytest.raises(ValueError, match="@handles"):
        watcher._youtube_vods("DylanPage")


def test_youtube_queues_bounded_slices_and_deduplicates(env, monkeypatch):
    youtube_env(env)
    monkeypatch.setattr(watcher, "_get", lambda *a, **k: pytest.fail("Twitch called"))
    monkeypatch.setattr(watcher, "_youtube_vods", lambda handle: [vod("yt1", "7h")])
    ids = watcher.scan(env.store, env.config, now=NOW)
    assert len(ids) == 2
    jobs = [env.store.get_job(job_id) for job_id in ids]
    assert all(job["platform"] == "youtube" for job in jobs)
    assert [(job["start_s"], job["end_s"]) for job in jobs] == [(0, 10800), (10800, 21600)]
    assert watcher.scan(env.store, env.config, now=NOW) == []


@pytest.mark.parametrize(
    "live,old,expected", [(False, False, 1), (True, False, 0), (False, True, 0)]
)
def test_youtube_live_and_source_cutoff(env, monkeypatch, live, old, expected):
    youtube_env(env)
    env.config.watch.max_vod_age_hours = 240
    entry = {**vod("yt1", created=NOW - timedelta(days=2) if old else NOW), "is_live": live}
    monkeypatch.setattr(watcher, "_youtube_vods", lambda handle: [entry])
    ids = watcher.scan(env.store, env.config, now=NOW)
    assert len(ids) == expected
    if ids:
        assert env.store.get_job(ids[0])["end_s"] == 3600


def test_youtube_failed_baseline_retried(env, monkeypatch):
    youtube_env(env)
    env.config.watch.baseline_on_first_run = True

    def fail(handle):
        raise ValueError("test failure")

    monkeypatch.setattr(watcher, "_youtube_vods", fail)
    assert watcher.scan(env.store, env.config, now=NOW) == []
    assert not env.store.get_meta("watch_baseline_done")
    monkeypatch.setattr(watcher, "_youtube_vods", lambda handle: [vod("yt1")])
    assert watcher.scan(env.store, env.config, now=NOW) == []
    assert env.store.get_meta("watch_baseline_done") == "1"
    assert len(env.store.list_jobs("skipped")) == 1
