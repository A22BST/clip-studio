"""Offline contract tests for multipart requests and defensive response handling."""

from email import policy
from email.parser import BytesParser

import httpx
import pytest
from autoclip.auto.config import UploadPostConfig
from autoclip.auto.uploadpost import Metrics, UploadPostClient, UploadPostError
from autoclip.stream.campaigns import Campaign


def multipart(request):
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.content
    )
    fields = {}
    for part in message.iter_parts():
        fields.setdefault(part.get_param("name", header="content-disposition"), []).append(
            part.get_payload(decode=True).decode()
        )
    return fields


def test_upload_fields(env):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"success": True, "request_id": "r1"})

    client = UploadPostClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        "https://api.test",
        "profile",
        config=UploadPostConfig(tiktok_privacy="SELF_ONLY", youtube_privacy="private"),
    )
    video = env.tmp / "video.mp4"
    video.write_bytes(b"video")
    result = client.upload(
        video,
        ["tiktok", "youtube", "instagram"],
        "T" * 110,
        "Caption",
        ["#GTA6", "gta6", "Extra"],
        Campaign(name="test", required_hashtags=["GTA6"], disclosure_required=True),
        "clip-1-post-2",
    )
    assert result.request_id == "r1"
    request = seen[0]
    assert str(request.url) == "https://api.test/api/upload"
    assert request.headers["Authorization"] == "Apikey fake-key"
    assert request.headers["Idempotency-Key"] == "clip-1-post-2"
    fields = multipart(request)
    assert fields["user"] == ["profile"]
    assert fields["platform[]"] == ["tiktok", "youtube", "instagram"]
    assert fields["video"] == ["video"]
    assert fields["title"] == fields["youtube_title"] == ["T" * 100]
    assert fields["description"] == fields["youtube_description"] == ["Caption #GTA6 #Extra"]
    assert fields["tiktok_title"] == fields["instagram_title"] == ["Caption #GTA6 #Extra"]
    assert fields["tags[]"] == ["GTA6", "Extra"]
    for name in ("async_upload", "disclose_commercial", "brand_content_toggle"):
        assert fields[name] == ["true"]
    assert fields["selfDeclaredMadeForKids"] == ["false"]
    assert fields["privacy_level"] == ["SELF_ONLY"]
    assert fields["privacyStatus"] == ["private"]
    assert fields["post_mode"] == ["DIRECT_POST"]
    assert fields["media_type"] == ["REELS"]


def test_caption_drops_optional_tags_first(env):
    seen = []
    client = UploadPostClient(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (
                    seen.append(multipart(request)) or httpx.Response(200, json={"request_id": "r"})
                )
            )
        )
    )
    video = env.tmp / "v.mp4"
    video.write_bytes(b"video")
    client.upload(
        video,
        ["tiktok"],
        "title",
        "C" * 2188,
        ["ExtraLongTag", "required"],
        Campaign(name="c", required_hashtags=["Required"]),
        "key",
    )
    assert seen[0]["tiktok_title"] == ["C" * 2188 + " #Required"]
    assert "disclose_commercial" not in seen[0]
    with pytest.raises(UploadPostError, match="limit"):
        client.upload(
            video,
            ["tiktok"],
            "t",
            "C" * 2200,
            [],
            Campaign(name="c", required_hashtags=["Required"]),
            "key",
        )


@pytest.mark.parametrize("status", [403, 429, 500])
def test_http_errors_never_echo_key(env, status):
    client = UploadPostClient(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text="Apikey fake-key")
            )
        )
    )
    with pytest.raises(UploadPostError) as error:
        client.status("r")
    assert "fake-key" not in str(error.value)
    assert error.value.status_code == status
    assert error.value.retryable == (status == 500)


def test_timeout_never_echoes_key(env):
    def handler(request):
        raise httpx.ReadTimeout("Apikey fake-key", request=request)

    client = UploadPostClient(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(UploadPostError) as error:
        client.status("r")
    assert "fake-key" not in str(error.value)
    assert error.value.retryable


def test_read_endpoints_and_nested_metrics(env):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"platform": "tiktok", "metrics": {"views": "1234", "likes": 8}},
                    {"youtube": {"nested": {"comments": 3, "shares": "invalid", "views": -1}}},
                    {"instagram": {"views": None, "likes": "bad"}},
                ]
            },
        )

    client = UploadPostClient(httpx.Client(transport=httpx.MockTransport(handler)))
    client.status("r")
    client.history("r")
    assert client.post_analytics("r") == {
        "tiktok": Metrics(1234, 8),
        "youtube": Metrics(comments=3),
    }
    assert seen[0].url.path == "/api/uploadposts/status"
    assert seen[1].url.path == "/api/uploadposts/history"
    assert seen[0].url.params["request_id"] == "r"
    assert seen[2].url.path == "/api/uploadposts/post-analytics/r"


def test_transient_error_preserves_request_id_without_echoing_body(env):
    client = UploadPostClient(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503, json={"request_id": "known", "message": "fake-key"}
                )
            )
        )
    )
    with pytest.raises(UploadPostError) as error:
        client.status("r")
    assert error.value.request_id == "known"
    assert "fake-key" not in str(error.value)


@pytest.mark.parametrize("body", ["not json", "null", "42"])
def test_invalid_json_shapes_are_safe_errors(env, body):
    client = UploadPostClient(
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)))
    )
    with pytest.raises(UploadPostError):
        client.status("r")
