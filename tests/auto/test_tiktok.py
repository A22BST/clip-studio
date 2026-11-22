"""Official TikTok adapter and routing tests; all HTTP uses MockTransport."""

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from autoclip.auto import secrets, tiktok
from autoclip.auto.cli import app
from autoclip.auto.config import TikTokConfig
from autoclip.auto.notify import RecordingNotifier
from autoclip.auto.poster import post_due
from autoclip.auto.uploadpost import UploadResult
from typer.testing import CliRunner


@pytest.fixture
def vault(monkeypatch):
    values = {
        secrets.TIKTOK_CLIENT_KEY: "client-sensitive",
        secrets.TIKTOK_CLIENT_SECRET: "secret-sensitive",
        secrets.TIKTOK_ACCESS_TOKEN: "access-sensitive",
        secrets.TIKTOK_REFRESH_TOKEN: "refresh-sensitive",
    }
    original = secrets.get_secret
    monkeypatch.setattr(
        secrets,
        "get_secret",
        lambda name: values.get(name) if name.startswith("TIKTOK_") else original(name),
    )
    monkeypatch.setattr(secrets, "set_secret", values.__setitem__)
    return values


def ok(data):
    return httpx.Response(200, json={"data": data, "error": {"code": "ok"}})


def publisher(env, handler, mode="inbox"):
    return tiktok.TikTokPublisher(
        httpx.Client(transport=httpx.MockTransport(handler)),
        store=env.store,
        config=TikTokConfig(mode=mode),
    )


def upload(client, path, key="clip-1-tiktok"):
    return client.upload(path, ["tiktok"], "title", "caption", ["tag"], None, key)


@pytest.mark.parametrize("size", [100, 4_999_999, 20_000_123, 65_000_000])
def test_init_chunks_and_durable_idempotency(env, vault, size):
    path = env.tmp / "video.mp4"
    with path.open("wb") as out:
        out.truncate(size)
    calls, chunks = [], []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert request.url.path.endswith("/inbox/video/init/")
            assert "post_info" not in body
            source = body["source_info"]
            assert source["total_chunk_count"] == max(1, size // min(size, tiktok.CHUNK))
            return ok(
                {
                    "publish_id": "pub",
                    "upload_url": "https://upload.tiktokapis.com/video/?upload_token=sensitive",
                }
            )
        assert "authorization" not in request.headers
        chunks.append((request.headers["content-range"], len(request.content)))
        return httpx.Response(201 if sum(n for _, n in chunks) == size else 206)

    client = publisher(env, handler)
    assert upload(client, path).request_id == "tiktok:pub"
    assert sum(n for _, n in chunks) == size
    assert chunks[-1][0].endswith(f"-{size - 1}/{size}")
    count = len(calls)
    assert upload(publisher(env, handler), path).request_id == "tiktok:pub"
    assert len(calls) == count
    assert "sensitive" not in env.store.path.read_bytes().decode("latin1")


def test_token_refresh_on_401_and_rotation(env, vault):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/oauth/token/"):
            assert b"refresh_token=refresh-sensitive" in request.content
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 7200,
                },
            )
        if len(calls) == 1:
            return httpx.Response(401, json={"error": {"code": "access_token_invalid"}})
        assert request.headers["authorization"] == "Bearer new-access"
        return ok({"privacy_level_options": ["SELF_ONLY"]})

    publisher(env, handler).creator_info()
    assert len(calls) == 3
    assert vault[secrets.TIKTOK_REFRESH_TOKEN] == "new-refresh"
    assert vault[secrets.TIKTOK_ACCESS_TOKEN] == "new-access"


@pytest.mark.parametrize(
    "code,status,retryable,fragment",
    [
        ("rate_limit_exceeded", 429, True, "rate limit"),
        ("spam_risk_too_many_pending_share", 403, False, "5 pending"),
        ("spam_risk_too_many_posts", 200, False, "daily"),
        ("unaudited_client_can_only_post_to_private_accounts", 403, False, "private account"),
        ("scope_not_authorized", 401, False, "scope"),
    ],
)
def test_safe_error_mapping(env, vault, capsys, caplog, code, status, retryable, fragment):
    def handler(request):
        return httpx.Response(status, json={"error": {"code": code, "message": "secret-sensitive"}})

    with pytest.raises(tiktok.TikTokError) as exc:
        publisher(env, handler).creator_info()
    assert fragment in str(exc.value)
    assert exc.value.retryable is retryable
    assert "secret-sensitive" not in str(exc.value) + caplog.text + capsys.readouterr().out


def test_ambiguous_init_is_not_repeated(env, vault):
    calls = []
    path = env.tmp / "v.mp4"
    path.write_bytes(b"video")

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret-sensitive", request=request)

    client = publisher(env, handler)
    for _ in range(2):
        with pytest.raises(tiktok.TikTokError):
            upload(client, path)
    assert len(calls) == 1


def test_chunk_failure_keeps_known_id(env, vault):
    path = env.tmp / "v.mp4"
    path.write_bytes(b"video")
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return ok({"publish_id": "pub", "upload_url": "https://upload.tiktokapis.com/v"})
        raise httpx.ReadTimeout("secret-sensitive", request=request)

    client = publisher(env, handler)
    with pytest.raises(tiktok.TikTokError) as exc:
        upload(client, path)
    assert exc.value.request_id == "tiktok:pub"
    assert upload(client, path).request_id == "tiktok:pub"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "state", ["SEND_TO_USER_INBOX", "PUBLISH_COMPLETE", "FAILED", "PROCESSING_UPLOAD"]
)
def test_status_mapping(env, vault, state):
    client = publisher(env, lambda r: ok({"status": state}))
    row = client.status("tiktok:pub")["results"][0]
    assert row["platform"] == "tiktok"
    if state == "SEND_TO_USER_INBOX":
        assert "not public" in row["message"]
    if state == "FAILED":
        assert row["success"] is False
    assert client.post_analytics("tiktok:pub") == {}


def test_direct_private_queries_creator_first(env, vault, monkeypatch):
    from autoclip.auto import gate

    monkeypatch.setattr(gate, "_probe_duration", lambda p: 30)
    calls = []
    path = env.tmp / "v.mp4"
    path.write_bytes(b"video")

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("creator_info/query/"):
            return ok(
                {
                    "privacy_level_options": ["SELF_ONLY", "FOLLOWER_OF_CREATOR"],
                    "max_video_post_duration_sec": 60,
                }
            )
        if request.method == "POST":
            assert json.loads(request.content)["post_info"]["privacy_level"] == "SELF_ONLY"
            return ok({"publish_id": "pub", "upload_url": "https://upload.tiktokapis.com/v"})
        return httpx.Response(201)

    upload(publisher(env, handler, "direct_private"), path)
    assert len(calls) == 3 and calls[0].url.path.endswith("creator_info/query/")


def test_direct_rejects_public_account(env, vault):
    path = env.tmp / "v.mp4"
    path.write_bytes(b"video")
    client = publisher(
        env,
        lambda r: ok({"privacy_level_options": ["SELF_ONLY", "PUBLIC_TO_EVERYONE"]}),
        "direct_private",
    )
    with pytest.raises(tiktok.TikTokError, match="private account"):
        upload(client, path)


def test_status_cli_read_only_and_secret_safe(env, vault, monkeypatch):
    writes = []
    monkeypatch.setattr(secrets, "set_secret", lambda *args: writes.append(args))
    monkeypatch.setattr(
        tiktok.TikTokPublisher,
        "creator_info",
        lambda self, refresh: (
            {"privacy_level_options": ["SELF_ONLY"]}
            if not refresh
            else pytest.fail("refresh requested")
        ),
    )
    result = CliRunner().invoke(app, ["tiktok-status"])
    assert result.exit_code == 0 and "present" in result.stdout
    assert not writes and not any(v in result.stdout for v in vault.values())


def test_login_pkce_and_denial_stores_nothing(vault, monkeypatch):
    writes, params = [], {}
    monkeypatch.setattr(secrets, "set_secret", lambda *args: writes.append(args))

    def browser(url):
        params.update(parse_qs(urlsplit(url).query))
        return True

    class Server:
        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 3455)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(tiktok, "HTTPServer", Server)
    monkeypatch.setattr(tiktok.webbrowser, "open", browser)
    monkeypatch.setattr(tiktok.random, "token_urlsafe", lambda n: "v" * 64 if n == 64 else "state")
    with pytest.raises(tiktok.TikTokError, match="timed out"):
        tiktok.login(timeout=0)
    assert params["code_challenge"] == [hashlib.sha256(("v" * 64).encode()).hexdigest()]
    assert params["scope"] == ["video.upload"] and not writes


@pytest.mark.parametrize("approve", [True, False])
def test_login_exchanges_only_after_matching_consent(vault, monkeypatch, approve):
    import io

    params, exchanges = {}, []

    def browser(url):
        params.update(parse_qs(urlsplit(url).query))
        return True

    class Server:
        def __init__(self, address, handler):
            self.handler = handler

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def handle_request(self):
            callback = object.__new__(self.handler)
            tail = "&code=approved-code" if approve else "&error=access_denied"
            callback.path = "/callback/?state=" + params["state"][0] + tail
            callback.send_response = lambda status: None
            callback.end_headers = lambda: None
            callback.wfile = io.BytesIO()
            callback.do_GET()

    def exchange(client, data):
        exchanges.append(data)

    monkeypatch.setattr(tiktok, "HTTPServer", Server)
    monkeypatch.setattr(tiktok.webbrowser, "open", browser)
    monkeypatch.setattr(tiktok, "_token_request", exchange)
    if approve:
        tiktok.login()
        assert exchanges[0]["code"] == "approved-code"
        verifier = exchanges[0]["code_verifier"]
        assert params["code_challenge"] == [hashlib.sha256(verifier.encode()).hexdigest()]
    else:
        with pytest.raises(tiktok.TikTokError, match="denied"):
            tiktok.login()
        assert not exchanges


def test_mixed_route_retry_retains_first_upload(env):
    class Provider:
        def __init__(self):
            self.calls = []

        def upload(self, **kwargs):
            self.calls.append(kwargs)
            return UploadResult("tiktok:pub")

    class Flaky(Provider):
        def upload(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise tiktok.TikTokError("temporary", retryable=True)
            return UploadResult("other")

    tt, other = Provider(), Flaky()
    router = tiktok.TikTokRouter(other, tt, env.store)
    args = {
        "video_path": "unused",
        "platforms": ["youtube", "tiktok"],
        "title": "t",
        "caption": "c",
        "hashtags": [],
        "campaign": None,
        "idempotency_key": "clip-1-youtube-tiktok",
    }
    with pytest.raises(tiktok.TikTokError):
        router.upload(**args)
    result = router.upload(**args)
    assert result.request_id.startswith("tiktok-route:")
    assert len(tt.calls) == 1 and len(other.calls) == 2
    assert tt.calls[0]["idempotency_key"] == "clip-1-tiktok"
    assert other.calls[0]["idempotency_key"] == "clip-1-youtube"


class Other:
    def __init__(self):
        self.uploads = []

    def upload(self, **kwargs):
        self.uploads.append(kwargs)
        return UploadResult("other")

    def status(self, rid):
        return {
            "results": [{"platform": "youtube", "success": True, "post_url": "https://yt.test/1"}]
        }

    def history(self, rid):
        return self.status(rid)


def test_poster_manual_fallback_missing_credentials(env, make_clip, vault):
    vault.clear()
    env.config.upload_post.manual_platforms = ["tiktok"]
    cid = make_clip(approve=True)
    now = datetime.now(UTC)
    env.store.enqueue_post(cid, now, ["tiktok", "youtube"])
    other, notifier = Other(), RecordingNotifier()
    post_due(
        env.store,
        env.config,
        notifier,
        other,
        now=now,
        gate_kwargs={"probe_duration": lambda p: 30},
        sleep=lambda _: None,
    )
    assert other.uploads[0]["platforms"] == ["youtube"]
    assert any("POST BY HAND on tiktok" in v[1] for v in notifier.videos)


def test_poster_tiktok_api_and_other_provider(env, make_clip, vault, monkeypatch):
    env.config.upload_post.manual_platforms = ["tiktok"]
    cid = make_clip(approve=True)
    now = datetime.now(UTC)
    env.store.enqueue_post(cid, now, ["tiktok", "youtube"])
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "PUT":
            return httpx.Response(201)
        if request.url.path.endswith("status/fetch/"):
            return ok({"status": "SEND_TO_USER_INBOX"})
        return ok({"publish_id": "pub", "upload_url": "https://upload.tiktokapis.com/v"})

    client = publisher(env, handler)
    monkeypatch.setattr(tiktok, "TikTokPublisher", lambda **kw: client)
    other, notifier = Other(), RecordingNotifier()
    result = post_due(
        env.store,
        env.config,
        notifier,
        other,
        now=now,
        gate_kwargs={"probe_duration": lambda p: 30},
        sleep=lambda _: None,
    )
    assert result and len(calls) == 3
    assert other.uploads[0]["platforms"] == ["youtube"]
    assert not notifier.videos
    assert any("not public" in text for text, _ in notifier.texts)
    assert any("Insane moment" in text for text, _ in notifier.texts)
