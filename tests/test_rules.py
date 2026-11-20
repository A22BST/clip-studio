"""Protect approval boundaries against accidental campaign weakening."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from autoclip.pipeline.rules import ClipFacts, check_clip
from autoclip.stream.campaigns import Campaign, load_campaign


def test_too_long_and_missing_tag() -> None:
    result = check_clip(Campaign(name="demo", required_hashtags=["#GTA6"]), ClipFacts(142))
    assert not result.passed
    assert result.qa_score == 0
    assert "duration 142.0s > max 90s" in [v.message for v in result.violations]
    assert any(v.code == "missing_hashtag" for v in result.violations)


def test_tags_mentions_and_duration_boundaries() -> None:
    campaign = Campaign(
        name="demo",
        min_duration_s=15,
        max_duration_s=90,
        required_hashtags=["#GTA6"],
        required_mentions=["@Creator"],
    )
    for duration in (15, 90):
        result = check_clip(campaign, ClipFacts(duration, hashtags=["gta6"], mentions=["CREATOR"]))
        assert result.passed and result.qa_score == 100
    result = check_clip(campaign, ClipFacts(14))
    assert {v.code for v in result.violations} >= {"too_short", "missing_mention"}


@pytest.mark.parametrize("policy", ["light", "strict", "none"])
@pytest.mark.parametrize("level", ["none", "reaction-to-spoiler", "raw-cinematic"])
def test_spoilers(policy: str, level: str) -> None:
    campaign = Campaign(name="demo", spoiler_policy=policy)
    result = check_clip(campaign, ClipFacts(30, spoiler_level=level))
    assert result.passed == (
        level != "raw-cinematic" and not (level == "reaction-to-spoiler" and policy == "strict")
    )
    if level == "reaction-to-spoiler" and policy == "light":
        assert result.qa_score == 90


def test_stream_age() -> None:
    now = datetime(2026, 11, 20, 12, tzinfo=UTC)
    campaign = Campaign(name="demo", today_only=True, max_age_hours=3)
    for source in (
        None,
        now - timedelta(days=1),
        now - timedelta(hours=4),
        now + timedelta(seconds=1),
    ):
        assert not check_clip(campaign, ClipFacts(30, source_stream_date=source, now=now)).passed
    assert check_clip(campaign, ClipFacts(30, source_stream_date=now, now=now)).passed
    # Naive datetimes deliberately mean UTC, including mixed-aware inputs.
    assert check_clip(
        campaign, ClipFacts(30, source_stream_date=now.replace(tzinfo=None), now=now)
    ).passed


@pytest.mark.parametrize("field", ["title", "caption", "hook", "transcript_text"])
def test_banned_content(field: str) -> None:
    campaign = Campaign(name="demo", banned_words=["bad"], banned_topics=["plot reveal"])
    result = check_clip(campaign, ClipFacts(30, **{field: "BAD plot REVEAL"}))
    assert {v.code for v in result.violations} == {"banned_word", "banned_topic"}
    assert check_clip(campaign, ClipFacts(30, title="badminton")).passed


def test_project_rules_and_title() -> None:
    result = check_clip(
        Campaign(name="demo", max_title_chars=3),
        ClipFacts(
            30,
            title="long",
            has_captions=False,
            has_hook=False,
            reframed=False,
        ),
    )
    assert {v.code for v in result.violations} == {
        "title_too_long",
        "missing_captions",
        "missing_hook",
        "missing_reframe",
    }


def test_yaml_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text("name: Demo\nmax_duration_s: 90\nplatforms: [tiktok]\n", encoding="utf-8")
    assert load_campaign(path).name == "Demo"
    assert load_campaign("demo", tmp_path).max_duration_s == 90
    monkeypatch.setenv("CLIPSTUDIO_CAMPAIGNS_DIR", str(tmp_path))
    assert load_campaign("demo").platforms == ["tiktok"]
    with pytest.raises(FileNotFoundError, match="Campaign file not found"):
        load_campaign("missing")


@pytest.mark.parametrize(
    "content",
    [
        "name: Demo\ntypo: true",
        "name: Demo\nplatforms: [twitter]",
        "name: Demo\nmin_duration_s: 100\nmax_duration_s: 90",
        "[]",
        "name: [",
        "name: Demo\nmax_age_hours: -1",
        "name: Demo\nswear_filter: unknown",
    ],
)
def test_invalid_yaml(tmp_path: Path, content: str) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Valid fields:.*name.*platforms"):
        load_campaign(path)


def test_shipped_example() -> None:
    assert load_campaign("example-gta-streamer").spoiler_policy == "light"
