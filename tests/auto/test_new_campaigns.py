import logging
from pathlib import Path

import pytest
import yaml
from autoclip.auto.campaign_meta import load_all_auto_campaigns, load_auto_campaign
from autoclip.pipeline.rules import ClipFacts, check_clip
from autoclip.stream.campaigns import load_campaign

DIRECTORY = Path(__file__).resolve().parents[2] / "campaigns"
EXPECTED = [
    (
        "dylan-page-marathon",
        "DylanPage",
        ["@dylan.page."],
        "youtube",
        4953,
        250,
        True,
        ["tiktok", "instagram", "youtube", "x"],
        1.2,
        "39753a1a-f1f3-491b-a8f6-0cfee0af0c97",
    ),
    (
        "asianjeff",
        "asianjeff",
        ["asianjeff"],
        "twitch",
        1840,
        300,
        True,
        ["tiktok", "instagram", "youtube", "x"],
        1.0,
        "bbd3a963-9a23-457c-bc15-6697971d9902",
    ),
    (
        "laurenhamden",
        "LaurenHamden",
        ["laurenhamdenn"],
        "twitch",
        4420,
        250,
        True,
        ["instagram"],
        1.5,
        "dd617572-f0f7-4754-8df5-4c0deb81763a",
    ),
    (
        "clipup-logo",
        "clipup",
        ["kreekcraft", "asianjeff", "laurenhamdenn"],
        "twitch",
        14917,
        150,
        False,
        ["instagram", "tiktok"],
        0.3,
        "802cf95a-ea84-4070-9a96-8a917831cb16",
    ),
]


@pytest.mark.parametrize(
    "key,tag,streamers,platform,budget,cap,active,platforms,rate,page", EXPECTED
)
def test_new_campaign_values(
    key, tag, streamers, platform, budget, cap, active, platforms, rate, page
):
    auto = load_auto_campaign(key, DIRECTORY)
    campaign = load_campaign(key, DIRECTORY)
    assert auto.campaign == campaign
    assert campaign.required_hashtags == [tag]
    assert not any(value.lstrip("#").lower() == "ad" for value in campaign.required_hashtags)
    assert campaign.disclosure_required is False
    assert (campaign.min_duration_s, campaign.max_duration_s) == (15, 60)
    assert campaign.platforms == platforms
    assert campaign.rate_per_1k_usd == rate
    assert campaign.required_overlay == ("clipup-logo.png" if key == "clipup-logo" else "")
    assert auto.meta.streamers == streamers
    assert auto.meta.platform == platform
    assert auto.meta.active is active
    assert auto.meta.ends_at is None
    assert auto.meta.budget_usd == budget
    assert auto.meta.cap_per_clip_usd == cap
    assert auto.meta.submit_url == f"https://contentrewards.com/c/campaigns/{page}"
    if key == "laurenhamden":
        assert campaign.required_caption_phrases == ["@LaurenHamden"]
        assert campaign.required_mentions == ["LaurenHamden"]
        assert "https://lozzahamden.click/" in campaign.notes
        assert "50%" in campaign.notes
        assert campaign.audience_geo == ""  # Account rule stays in notes only.
    if key == "dylan-page-marathon":
        assert campaign.camera_box == (0.684, 0.148, 0.87, 0.459)
        assert campaign.camera_split == 0.45
        assert "WHOLE clip" in campaign.notes
        assert "facecam" in campaign.notes
        assert campaign.no_ai_visuals
    else:
        assert campaign.camera_box is None and campaign.camera_split is None
    if key in {"dylan-page-marathon", "asianjeff"}:
        assert auto.meta.starts_at.isoformat() == "2026-11-19"
    facts = ClipFacts(
        duration_s=30,
        hashtags=[tag],
        caption=" ".join(campaign.required_caption_phrases),
        mentions=campaign.required_mentions,
        overlay_applied=key == "clipup-logo",
    )
    assert check_clip(campaign, facts).passed
    if campaign.required_caption_phrases:
        facts.caption = ""
        assert not check_clip(campaign, facts).passed
        facts.caption = " ".join(campaign.required_caption_phrases)
    facts.hashtags = []
    assert not check_clip(campaign, facts).passed


def test_missing_clipup_asset_warns_without_failing_load(tmp_path, caplog):
    # Independent of whether the owner has subsequently installed the real logo.
    data = yaml.safe_load((DIRECTORY / "clipup-logo.yaml").read_text(encoding="utf-8"))
    (tmp_path / "clipup-logo.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        campaign = load_campaign("clipup-logo", tmp_path)
    assert campaign.required_overlay == "clipup-logo.png"
    assert any(
        record.levelno == logging.WARNING and "clipup-logo.png" in record.message
        for record in caplog.records
    )


def test_all_four_discovered():
    found = {campaign.key for campaign in load_all_auto_campaigns(DIRECTORY)}
    assert {row[0] for row in EXPECTED} <= found
