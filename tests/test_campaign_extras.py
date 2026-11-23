from autoclip.pipeline import captions
from autoclip.pipeline.rules import ClipFacts, check_clip
from autoclip.pipeline.transcript import Word
from autoclip.stream.campaigns import Campaign
import pytest


def _campaign(**kw):
    return Campaign(name="c", min_duration_s=10, max_duration_s=90, **kw)


def _facts(**kw):
    base = {"duration_s": 30, "title": "t", "hook": "h", "caption": "c"}
    base.update(kw)
    return ClipFacts(**base)


def test_defaults_unchanged_for_plain_campaign():
    assert check_clip(_campaign(), _facts()).passed


@pytest.mark.parametrize("box", [
    [-0.1, 0, 1, 1], [0, 0, 1.1, 1], [0.8, 0, 0.2, 1],
    [0, 0.5, 1, 0.5], [0, 0, 1], [0, 0, float("nan"), 1],
])
def test_invalid_manual_camera_bounds(box):
    with pytest.raises(ValueError):
        _campaign(camera_box=box)


@pytest.mark.parametrize("split", [0, 1, float("inf")])
def test_invalid_camera_split(split):
    with pytest.raises(ValueError):
        _campaign(camera_split=split)


def test_disclosure_required_blocks_without_it():
    camp = _campaign(disclosure_required=True)
    res = check_clip(camp, _facts())
    assert not res.passed and any(v.code == "missing_disclosure" for v in res.violations)
    assert check_clip(camp, _facts(disclosure_shown=True)).passed


def test_required_overlay_and_caption_phrase_block():
    camp = _campaign(
        required_overlay="kreek.png", required_caption_phrases=["Watch Kreek on YouTube"]
    )
    res = check_clip(camp, _facts())
    codes = {v.code for v in res.violations}
    assert {"missing_overlay", "missing_caption_phrase"} <= codes
    ok = check_clip(camp, _facts(overlay_applied=True, caption="watch kreek on youtube and twitch"))
    assert ok.passed


def test_no_ai_visuals_guard():
    assert not check_clip(_campaign(no_ai_visuals=True), _facts(ai_visuals=True)).passed


def test_required_tags_alias_merges():
    camp = Campaign.model_validate(
        {"name": "c", "required_hashtags": ["GTA6"], "required_tags": ["Kreek"]}
    )
    assert camp.required_hashtags == ["GTA6", "Kreek"]


def test_disclosure_event_in_ass():
    subs = captions.build_ass(
        [Word("hi", 0.0, 0.4)], captions.get_style("bold_pop"), width=1080, height=1920,
        disclosure_text="#ad {\evil}", disclosure_duration_s=3.0,
    )  # fmt: skip
    events = [e for e in subs.events if e.style == captions.DISCLOSURE_STYLE_NAME]
    assert len(events) == 1 and events[0].end == 3000 and "evil" in events[0].text
    assert events[0].text.startswith(r"{\fad(120,120)}")  # a real fade tag, not a form feed
    assert "\x0c" not in events[0].text
    assert "evil" in events[0].text and "\evil" not in events[0].text[len(r"{\fad(120,120)}") :]
