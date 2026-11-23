"""Semantic selection, speech safety, model validation and persistent rotation."""

import json
from pathlib import Path

import pytest

from autoclip.pipeline import sfx, sfx_auto
from autoclip.pipeline.sfx_catalog import CATALOG
from autoclip.pipeline.transcript import Transcript, Word


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path))
    root = sfx.library_dir()
    root.mkdir(parents=True)
    for name in CATALOG:
        (root / f"{name}.wav").touch()
    monkeypatch.setattr(sfx_auto, "loudness_onsets", lambda *a: [])
    return root


def test_catalogue_complete(library):
    assert len(CATALOG) == 25
    assert set(sfx.available_names()) == set(CATALOG)
    actual = Path("D:/autoclip/assets/sfx/viral-clip-sound-effects")
    if actual.exists():
        assets = {p.stem for p in actual.iterdir() if p.suffix.lower() in {".wav", ".mp3", ".ogg", ".flac", ".m4a"}}
        assert assets == set(CATALOG)
    assert all(category and use and avoid for category, use, avoid in CATALOG.values())


@pytest.mark.parametrize("text,expected", [
    ("Shark attack: he was mauled", "IMPACT"),
    ("He found Bigfoot", "REVEAL"),
    ('free PS5: chat floods with me', "NOTIFICATION"),
    ("He pulls off a brutal heist section", "SPOTLIGHT"),
    ("He won a million cash payout", "MONEY"),
    ("oops a funny fail", "FAIL"),
    ("An awkward flirt", "AWKWARD"),
    ("His reaction to that moment", None),
    ("The screenshot of the desktop", None),
    ("Serious sad news of a real death", None),
])
def test_category(text, expected):
    assert sfx_auto.choose_category(text) == expected


def suggest(words=(), **kwargs):
    return sfx_auto.suggest_events("unused.wav", 100, 120, "seed",
        story={"payoff": {"start_s": 106, "end_s": 108, "text": "he crashed"}},
        transcript=Transcript(words=list(words)), **kwargs)


def test_anchor_without_peak(library):
    assert suggest()[0]["at_s"] == 6


def test_snap_only_near_anchor(library, monkeypatch):
    monkeypatch.setattr(sfx_auto, "loudness_onsets", lambda *a: [(5, 7), (12, 40)])
    assert suggest()[0]["at_s"] == 5


def test_move_to_next_word_gap(library):
    words = [Word("crash", 105.8, 106.2), Word("wow", 107, 107.2)]
    assert suggest(words)[0]["at_s"] == pytest.approx(6.6)
    assert not sfx_auto.overlaps_speech(6.6, words, 100)


def test_drop_continuous_speech(library):
    assert suggest([Word("talking", 105, 108)]) == []


def test_loud_onset_exception(library, monkeypatch):
    monkeypatch.setattr(sfx_auto, "loudness_onsets", lambda *a: [(6, 10)])
    assert suggest([Word("screaming", 105, 108)])[0]["at_s"] == 6


def test_subthreshold_onset_cannot_mask_speech(library, monkeypatch):
    monkeypatch.setattr(sfx_auto, "loudness_onsets", lambda *a: [(6, 9.9)])
    assert suggest([Word("talking", 105, 108)]) == []


def test_rotation_persists_and_preview_does_not_write(library):
    names = [suggest()[0]["name"] for _ in range(12)]
    assert all(a != b for a, b in zip(names, names[1:]))
    assert len(set(names[:3])) == 3
    before = (library / "recent.json").read_bytes()
    suggest(record=False)
    assert (library / "recent.json").read_bytes() == before
    assert json.loads(before) == names[-6:]


def test_single_asset_category_drops_repeat(library):
    kwargs = dict(story={"payoff": {"start_s": 6, "text": "money"}}, transcript=[])
    assert sfx_auto.suggest_events("unused", 0, 20, "a", **kwargs)
    assert sfx_auto.suggest_events("unused", 0, 20, "b", **kwargs) == []


def test_fallback_payoff_transcript(library, monkeypatch):
    monkeypatch.setattr(sfx_auto, "loudness_onsets", lambda *a: [(6, 15)])
    words = Transcript(words=[Word("discovered", 5.8, 6.5)])
    event, = sfx_auto.suggest_events("unused", 0, 20, "a", transcript=words)
    assert CATALOG[event["name"]][0] == "REVEAL"


@pytest.mark.parametrize("name,kind,text,words,reason", [
    ("ROBLOX", "impact", "mauled by a shark", [], "category"),
    ("PIANO MEME", "impact", "discovered roaches", [], "category"),
    ("MEME BOOM", "impact", "oh no", [], "category"),
    ("MEME BOOM", "impact", "that is so funny", [], "category"),
    ("Riser 2", "impact", "crashed", [], "riser"),
    ("Boom", "impact", "crashed", [Word("speech", 5, 8)], "speech"),
    ("FAH", "impact", "a serious sad fail", [], "category"),
])
def test_model_validation(library, name, kind, text, words, reason):
    events, notes = sfx_auto.validate_events([{"name": name, "kind": kind, "at_s": 6}],
        "unused", 0, 20, story={"payoff": {"start_s": 6, "text": text}}, transcript=words)
    assert events == [] and reason in notes[0]


def test_model_valid_pick_and_repeat(library):
    event = [{"name": "Boom", "at_s": 6}]
    kwargs = dict(story={"payoff": {"start_s": 6, "text": "crash"}}, transcript=[])
    assert sfx_auto.validate_events(event, "unused", 0, 20, **kwargs) == (event, [])
    rejected, notes = sfx_auto.validate_events(event, "unused", 0, 20, **kwargs)
    assert not rejected and "repeats" in notes[0]


def test_riser_checks_actual_start(library, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(sfx_auto.ffmpeg, "probe", lambda *a: SimpleNamespace(duration_s=4))
    events, notes = sfx_auto.validate_events([{"name": "Riser 2", "kind": "riser", "at_s": 6}],
        "unused", 0, 20, story={"payoff": {"start_s": 6, "text": "crash"}}, transcript=[])
    assert events == [] and "first 3" in notes[0]
