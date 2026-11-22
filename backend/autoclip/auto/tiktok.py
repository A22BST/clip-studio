"""Official Content Posting API only. No automatic retries of ambiguous init requests."""

from __future__ import annotations

import hashlib
import json
import secrets as random
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from . import secrets
from .config import TikTokConfig
from .store import Store
from .uploadpost import UploadPostError, UploadResult

API = "https://open.tiktokapis.com/v2"
REDIRECT = "http://127.0.0.1:3455/callback/"
CHUNK = 10_000_000
INBOX_MESSAGE = "Open TikTok inbox notification, finish editing and publish; not public yet."
PRIVATE_MESSAGE = "Private post ready. Open TikTok and change visibility to publish publicly."


class TikTokError(UploadPostError):
    """Only fixed messages and recognized codes may escape the adapter."""


ERRORS = {
    "rate_limit_exceeded": "TikTok rate limit; try later",
    "spam_risk_too_many_pending_share": "TikTok allows at most 5 pending shares per 24 hours",
    "spam_risk_too_many_posts": "TikTok daily posting cap reached",
    "spam_risk_user_banned_from_posting": "TikTok creator is banned from posting",
    "reached_active_user_cap": "TikTok active creator cap reached",
    "unaudited_client_can_only_post_to_private_accounts": (
        "Unaudited Direct Post requires a private account and SELF_ONLY"
    ),
    "privacy_level_option_mismatch": "TikTok privacy setting is unavailable",
    "scope_not_authorized": (
        "TikTok scope not authorized; approve the required scope and log in again"
    ),
    "access_token_invalid": "TikTok token expired; log in again",
    "url_ownership_unverified": "TikTok URL ownership is not verified",
}


def credentials_ready() -> bool:
    return all(
        secrets.secret_is_set(n)
        for n in (
            secrets.TIKTOK_CLIENT_KEY,
            secrets.TIKTOK_CLIENT_SECRET,
        )
    ) and any(
        secrets.secret_is_set(n)
        for n in (
            secrets.TIKTOK_ACCESS_TOKEN,
            secrets.TIKTOK_REFRESH_TOKEN,
        )
    )


def _decode(response):
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        raise TikTokError("TikTok returned an invalid response") from None
    error = body.get("error", {})
    code = error.get("code", "ok") if isinstance(error, dict) else error
    if response.is_error or code != "ok":
        raise TikTokError(
            ERRORS.get(code, "TikTok request failed"),
            status_code=response.status_code,
            retryable=response.status_code == 429 or code == "rate_limit_exceeded",
        )
    return body


def _token_request(client, data):
    data = {
        "client_key": secrets.require_secret(secrets.TIKTOK_CLIENT_KEY),
        "client_secret": secrets.require_secret(secrets.TIKTOK_CLIENT_SECRET),
        **data,
    }
    try:
        body = _decode(client.post(API + "/oauth/token/", data=data, timeout=30))
    except httpx.HTTPError:
        raise TikTokError("TikTok token transport error") from None
    if not body.get("access_token") or not body.get("refresh_token"):
        raise TikTokError("TikTok token response is incomplete")
    # Rotation must be persisted, never placed in the posting database.
    try:
        secrets.set_secret(secrets.TIKTOK_REFRESH_TOKEN, body["refresh_token"])
        secrets.set_secret(secrets.TIKTOK_ACCESS_TOKEN, body["access_token"])
    except RuntimeError:
        raise TikTokError("Could not persist TikTok tokens; log in again") from None
    return body


class TikTokPublisher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        config: TikTokConfig | None = None,
        store: Store | None = None,
    ):
        secrets.harden_logging()
        self._client = client or httpx.Client(timeout=60, follow_redirects=False)
        self.config = config or TikTokConfig()
        self.store = store or Store()

    def _call(self, path, data=None, *, refresh=True):
        token = secrets.get_secret(secrets.TIKTOK_ACCESS_TOKEN)
        if not token and refresh:
            self._refresh()
            return self._call(path, data, refresh=False)
        if not token:
            raise TikTokError("TikTok credentials are missing")
        try:
            response = self._client.post(
                API + path,
                json=data or {},
                timeout=60,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            # Init may have been accepted: never automatically repeat it.
            raise TikTokError("TikTok transport error; check TikTok before retrying") from None
        if response.status_code == 401 and refresh:
            try:
                code = response.json().get("error", {}).get("code")
            except (ValueError, AttributeError):
                code = None
            if code == "access_token_invalid":
                self._refresh()
                return self._call(path, data, refresh=False)
        return _decode(response).get("data", {})

    def _refresh(self):
        try:
            _token_request(
                self._client,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": secrets.require_secret(secrets.TIKTOK_REFRESH_TOKEN),
                },
            )
        except secrets.MissingSecretError:
            raise TikTokError("TikTok credentials are missing; log in again") from None

    def creator_info(self, *, refresh=True):
        return self._call("/post/publish/creator_info/query/", refresh=refresh)

    def upload(self, video_path, platforms, title, caption, hashtags, campaign, idempotency_key):
        if platforms != ["tiktok"]:
            raise TikTokError("TikTokPublisher accepts only tiktok")
        key = "tiktok:upload:" + idempotency_key
        known = self.store.get_meta(key)
        if known:
            if known == "initializing":
                raise TikTokError(
                    "TikTok init outcome uncertain; check TikTok before manual recovery"
                )
            return UploadResult(known)
        path = Path(video_path)
        size = path.stat().st_size
        if not 0 < size <= 4_000_000_000:
            raise TikTokError("TikTok video must be nonempty and at most 4 GB")
        mime = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}.get(
            path.suffix.lower()
        )
        if not mime:
            raise TikTokError("TikTok requires MP4, MOV or WebM")
        chunk_size = min(size, CHUNK)
        count = max(1, size // chunk_size)
        body = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": count,
            }
        }
        endpoint = "/post/publish/inbox/video/init/"
        if self.config.mode == "direct_private":
            info = self.creator_info()
            options = info.get("privacy_level_options", [])
            if "SELF_ONLY" not in options or "PUBLIC_TO_EVERYONE" in options:
                raise TikTokError(ERRORS["unaudited_client_can_only_post_to_private_accounts"])
            from .gate import _probe_duration

            if _probe_duration(path) > info.get("max_video_post_duration_sec", 0):
                raise TikTokError("Video exceeds TikTok creator duration limit")
            campaign_info = getattr(campaign, "campaign", campaign)
            tags = list(
                dict.fromkeys([*getattr(campaign_info, "required_hashtags", []), *hashtags])
            )
            text = " ".join([caption or title, *("#" + t.lstrip("#") for t in tags)])
            if len(text.encode("utf-16-le")) // 2 > 2200:
                raise TikTokError("TikTok caption exceeds 2200 UTF-16 units")
            body["post_info"] = {
                "title": text,
                "privacy_level": "SELF_ONLY",
                "disable_comment": True,
                "disable_duet": True,
                "disable_stitch": True,
            }
            endpoint = "/post/publish/video/init/"
        # Durable reservation prevents a crash/timeout from silently creating another share.
        with self.store._conn() as con:
            inserted = con.execute(
                "INSERT OR IGNORE INTO meta(key,value) VALUES (?,?)", (key, "initializing")
            ).rowcount
        if not inserted:
            return self.upload(
                video_path, platforms, title, caption, hashtags, campaign, idempotency_key
            )
        try:
            init = self._call(endpoint, body)
        except TikTokError as exc:
            # A definite API rejection has no publish ID and is safe to retry later.
            if exc.status_code is not None and exc.status_code < 500:
                self.store.set_meta(key, "")
                with self.store._conn() as con:
                    con.execute("DELETE FROM meta WHERE key=? AND value=''", (key,))
            raise
        publish_id = init.get("publish_id")
        if not publish_id:
            raise TikTokError("TikTok init response is incomplete; check TikTok before retrying")
        request_id = "tiktok:" + publish_id
        self.store.set_meta(key, request_id)
        url = init.get("upload_url", "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".tiktokapis.com"):
            raise TikTokError(
                "TikTok returned an invalid upload destination", request_id=request_id
            )
        try:
            with path.open("rb") as video:
                offset = 0
                for index in range(count):
                    length = size - offset if index == count - 1 else chunk_size
                    response = self._client.put(
                        url,
                        content=video.read(length),
                        timeout=240,
                        headers={
                            "Content-Type": mime,
                            "Content-Length": str(length),
                            "Content-Range": f"bytes {offset}-{offset + length - 1}/{size}",
                        },
                    )
                    if response.status_code != (201 if index == count - 1 else 206):
                        raise TikTokError("TikTok chunk upload failed", request_id=request_id)
                    offset += length
        except (httpx.HTTPError, OSError):
            raise TikTokError(
                "TikTok chunk transfer interrupted; existing share retained", request_id=request_id
            ) from None
        return UploadResult(request_id)

    def status(self, request_id):
        data = self._call(
            "/post/publish/status/fetch/", {"publish_id": request_id.removeprefix("tiktok:")}
        )
        state = data.get("status")
        row = {"platform": "tiktok"}
        if state == "FAILED":
            row.update(success=False, message="TikTok processing failed; check TikTok")
        elif state == "SEND_TO_USER_INBOX":
            row.update(
                success=True, post_url="(TikTok inbox; awaiting publication)", message=INBOX_MESSAGE
            )
        elif state == "PUBLISH_COMPLETE":
            ids = data.get("publicaly_available_post_id", [])
            public_id = str(ids[0]) if ids else ""
            url = (
                f"https://www.tiktok.com/@_/video/{public_id}"
                if public_id.isdigit()
                else "(TikTok private post)"
            )
            row.update(
                success=True, post_url=url, message=PRIVATE_MESSAGE if not ids else "Published"
            )
        return {"status": "failed" if state == "FAILED" else state, "results": [row]}

    def history(self, request_id):
        # Content Posting has no history endpoint; fetch the known publish ID.
        return self.status(request_id)["results"]

    def post_analytics(self, request_id):
        # Display API permissions are separate. Never invent zero engagement counts.
        return {}


class TikTokRouter:
    """Persist separate provider IDs for mixed-platform posts; preserve existing IDs."""

    def __init__(self, other, tiktok, store, *, enabled=True):
        self.other, self.tiktok, self.store = other, tiktok, store
        self.enabled = enabled

    def upload(self, **kwargs):
        platforms = kwargs["platforms"]
        if not self.enabled or "tiktok" not in platforms:
            return self.other.upload(**kwargs)
        if platforms == ["tiktok"]:
            return self.tiktok.upload(**kwargs)
        key = "tiktok-route:" + kwargs["idempotency_key"]
        state = json.loads(self.store.get_meta(key) or "{}")
        base_key = kwargs["idempotency_key"].removesuffix("-" + "-".join(platforms))
        for provider, subset in (
            ("tiktok", ["tiktok"]),
            ("other", [p for p in platforms if p != "tiktok"]),
        ):
            if provider in state:
                continue
            try:
                result = getattr(self, provider).upload(
                    **{
                        **kwargs,
                        "platforms": subset,
                        "idempotency_key": base_key + "-" + "-".join(subset),
                    }
                )
                state[provider] = result.request_id
                self.store.set_meta(key, json.dumps(state))
            except UploadPostError as exc:
                if exc.request_id:
                    state[provider] = exc.request_id
                    self.store.set_meta(key, json.dumps(state))
                # No combined request ID until all providers have initialized. Durable state
                # resumes only the missing provider on the next gated attempt.
                raise TikTokError(
                    "Platform upload incomplete; existing uploads retained",
                    retryable=bool(state) or exc.retryable,
                ) from None
        return UploadResult("tiktok-route:" + json.dumps(state, sort_keys=True))

    def _read(self, method, request_id):
        if request_id.startswith("tiktok-route:"):
            rows = []
            for provider, rid in json.loads(request_id.removeprefix("tiktok-route:")).items():
                payload = getattr(getattr(self, provider), method)(rid)
                rows.extend(payload if isinstance(payload, list) else payload.get("results", []))
            return {"results": rows}
        target = self.tiktok if request_id.startswith("tiktok:") else self.other
        return getattr(target, method)(request_id)

    def status(self, request_id):
        return self._read("status", request_id)

    def history(self, request_id):
        return self._read("history", request_id)

    def post_analytics(self, request_id):
        return {} if request_id.startswith("tiktok") else self.other.post_analytics(request_id)


def login(*, mode="inbox", timeout=180):
    """Interactive desktop PKCE only; no exchange or storage before consent callback."""
    secrets.harden_logging()
    client_key = secrets.require_secret(secrets.TIKTOK_CLIENT_KEY)
    secrets.require_secret(secrets.TIKTOK_CLIENT_SECRET)
    verifier, state = random.token_urlsafe(64), random.token_urlsafe(32)
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Request paths contain authorization codes.

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            valid = parsed.path == "/callback/" and random.compare_digest(
                query.get("state", [""])[0], state
            )
            if valid:
                result["code"] = query.get("code", [""])[0]
                result["denied"] = "error" in query
            self.send_response(200 if valid else 400)
            self.end_headers()
            self.wfile.write(
                b"Authorization received. Return to clip-auto." if valid else b"Invalid callback."
            )

    scope = "video.upload" if mode == "inbox" else "video.publish"
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": REDIRECT,
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": hashlib.sha256(verifier.encode()).hexdigest(),
    }
    with HTTPServer(("127.0.0.1", 3455), Callback) as server:
        server.timeout = 1
        if not webbrowser.open("https://www.tiktok.com/v2/auth/authorize/?" + urlencode(params)):
            raise TikTokError("Could not open browser; run from an interactive desktop")
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if result.get("denied") or not result.get("code"):
        raise TikTokError("TikTok approval denied or timed out; no tokens stored")
    with httpx.Client(timeout=30) as client:
        _token_request(
            client,
            {
                "grant_type": "authorization_code",
                "code": result["code"],
                "redirect_uri": REDIRECT,
                "code_verifier": verifier,
            },
        )
