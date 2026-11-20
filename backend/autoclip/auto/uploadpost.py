"""Small, secret-safe Upload-Post adapter. No automatic upload retries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..stream.campaigns import Campaign
from . import secrets
from .campaign_meta import AutoCampaign
from .config import UploadPostConfig


@dataclass(frozen=True)
class Metrics:
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0


@dataclass(frozen=True)
class UploadResult:
    request_id: str
    immediate_results: list[dict[str, Any]] = field(default_factory=list)


class UploadPostError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.retryable = retryable


def _tags(values):
    out, seen = [], set()
    for value in values:
        tag = str(value).strip().lstrip("#")
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append("#" + tag)
    return out


def _caption(caption, hashtags, campaign, limit):
    required = _tags(campaign.required_hashtags)
    tags = _tags([*required, *hashtags])
    required_keys = {t.casefold() for t in required}
    optional = [t for t in tags if t.casefold() not in required_keys]

    def render():
        return " ".join([caption.strip(), *required, *optional]).strip()

    while optional and len(render()) > limit:
        optional.pop()
    if len(render()) > limit:
        # Do not silently strip campaign wording or required hashtags.
        raise UploadPostError("Caption and required hashtags exceed the platform limit")
    return render()


class UploadPostClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://api.upload-post.com",
        profile: str = "crazyheist",
        *,
        config: UploadPostConfig | None = None,
    ) -> None:
        self._client = client or httpx.Client(timeout=240)
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self.config = config or UploadPostConfig()

    def _call(self, method, path, **kwargs):
        try:
            key = secrets.require_secret(secrets.UPLOAD_POST_API_KEY)
        except secrets.MissingSecretError:
            raise UploadPostError("Upload-Post API key is not configured") from None
        headers = {"Authorization": f"Apikey {key}", **kwargs.pop("headers", {})}
        try:
            response = self._client.request(method, self.base_url + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise UploadPostError("Upload-Post transport error", retryable=True) from None
        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = {}
            request_id = str(body.get("request_id") or "") if isinstance(body, dict) else ""
            reason = {403: "platform unavailable on plan", 429: "monthly limit reached"}.get(
                response.status_code, "request failed"
            )
            raise UploadPostError(
                f"Upload-Post HTTP {response.status_code}: {reason}",
                status_code=response.status_code,
                request_id=request_id,
                retryable=response.status_code >= 500,
            )
        try:
            data = response.json()
        except ValueError:
            raise UploadPostError("Upload-Post invalid JSON", retryable=True) from None
        if not isinstance(data, (dict, list)):
            raise UploadPostError("Upload-Post unexpected response", retryable=True)
        return data

    def upload(
        self,
        video_path: Path | str,
        platforms: list[str],
        title: str,
        caption: str,
        hashtags: list[str],
        campaign: AutoCampaign | Campaign,
        idempotency_key: str,
    ) -> UploadResult:
        campaign = getattr(campaign, "campaign", campaign)
        fields = [("user", self.profile), ("title", title[:100]), ("async_upload", "true")]
        fields += [("platform[]", p) for p in platforms]
        fields.append(("description", _caption(caption, hashtags, campaign, 5000)))
        if "tiktok" in platforms:
            fields += [
                ("tiktok_title", _caption(caption, hashtags, campaign, 2200)),
                ("privacy_level", self.config.tiktok_privacy),
                ("post_mode", self.config.tiktok_post_mode),
            ]
            if campaign.disclosure_required:
                fields += [("disclose_commercial", "true"), ("brand_content_toggle", "true")]
        if "youtube" in platforms:
            fields += [
                ("youtube_title", title[:100]),
                ("youtube_description", _caption(caption, hashtags, campaign, 5000)),
                ("privacyStatus", self.config.youtube_privacy),
                ("selfDeclaredMadeForKids", "false"),
            ]
            fields += [("tags[]", t[1:]) for t in _tags([*campaign.required_hashtags, *hashtags])]
        if "instagram" in platforms:
            fields += [
                ("instagram_title", _caption(caption, hashtags, campaign, 2200)),
                ("media_type", "REELS"),
            ]
        try:
            with Path(video_path).open("rb") as handle:
                data = self._call(
                    "POST",
                    "/api/upload",
                    headers={"Idempotency-Key": idempotency_key},
                    files=[
                        *((k, (None, v)) for k, v in fields),
                        ("video", (Path(video_path).name, handle, "video/mp4")),
                    ],
                )
        except OSError:
            raise UploadPostError("Upload-Post video file unavailable") from None
        if not isinstance(data, dict):
            raise UploadPostError("Upload-Post unexpected upload response", retryable=True)
        request_id = str(data.get("request_id") or "")
        if data.get("success") is False:
            raise UploadPostError("Upload-Post rejected upload", request_id=request_id)
        results = data.get("results", [])
        if not request_id:
            raise UploadPostError("Upload-Post missing request ID", retryable=True)
        return UploadResult(request_id, results if isinstance(results, list) else [])

    def status(self, request_id: str) -> dict | list:
        return self._call(
            "GET", "/api/uploadposts/status", params={"request_id": request_id}, timeout=15
        )

    def history(self, request_id: str) -> dict | list:
        return self._call(
            "GET", "/api/uploadposts/history", params={"request_id": request_id}, timeout=15
        )

    def post_analytics(self, request_id: str) -> dict[str, Metrics]:
        from urllib.parse import quote

        data = self._call("GET", "/api/uploadposts/post-analytics/" + quote(request_id, safe=""))
        collected: dict[str, dict[str, int]] = {}

        def walk(node, platform=None):
            if isinstance(node, list):
                for item in node:
                    walk(item, platform)
            elif isinstance(node, dict):
                platform = node.get("platform", platform)
                if platform in ("tiktok", "youtube", "instagram"):
                    for name in ("views", "likes", "comments", "shares"):
                        if name in node:
                            try:
                                value = max(0, int(node[name]))
                            except (ValueError, TypeError, OverflowError):
                                continue
                            collected.setdefault(platform, {})[name] = value
                for key, value in node.items():
                    walk(value, key if key in ("tiktok", "youtube", "instagram") else platform)

        walk(data)
        return {platform: Metrics(**values) for platform, values in collected.items()}
