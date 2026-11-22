"""Deterministic chain story envelopes use measured words within candidates."""

from copy import deepcopy

import pytest
from autoclip.auto.select import _pad_story_picks
from autoclip.pipeline.boundaries import refine
from autoclip.pipeline.highlights import StoryPick, check_story
from autoclip.pipeline.transcript import Transcript, Word


def pad(*, setup=12.2, payoff=32.2, lo=0, hi=119, minimum=20, maximum=90):
    transcript = Transcript(words=[Word("word.", i, i + 0.8) for i in range(120)])
    pick = {
        "start_word_index": max(lo, int(setup)),
        "end_word_index": min(hi, int(payoff)),
        "story": {
            "setup": {"start_s": setup, "end_s": setup + 1, "text": "setup"},
            "change": {"start_s": setup + 2, "end_s": setup + 3, "text": "change"},
            "payoff": {"start_s": payoff - 1, "end_s": payoff, "text": "payoff"},
        },
    }
    story = deepcopy(pick["story"])
    data = {"candidates": [{"first_word": lo, "last_word": hi}],
            "limits": {"min_duration_s": minimum, "max_duration_s": maximum}}
    _pad_story_picks({"clips": [pick]}, data, transcript)
    assert pick["story"] == story
    return pick, transcript


def test_measured_padding_preserves_payoff_through_refinement():
    pick, transcript = pad()
    assert pick["start_word_index"] == 11  # first start >= 10.2
    assert pick["end_word_index"] == 33  # last end <= 34.7
    bounds = transcript.time_range(pick["start_word_index"], pick["end_word_index"])
    assert bounds[1] - pick["story"]["payoff"]["end_s"] >= 1
    model = StoryPick.model_validate(pick)
    assert check_story(model, bounds, transcript.words, []).status == "ok"
    boundary = refine(transcript, pick["start_word_index"], pick["end_word_index"], pick=model)
    assert boundary is not None
    assert check_story(model, boundary, transcript.words, []).status == "ok"


def test_padding_respects_candidate_edges():
    pick, _ = pad(lo=12, hi=33)
    assert (pick["start_word_index"], pick["end_word_index"]) == (12, 33)


def test_maximum_trims_head_and_preserves_tail():
    pick, transcript = pad(setup=12.2, payoff=100.2, maximum=40)
    start, end = transcript.time_range(pick["start_word_index"], pick["end_word_index"])
    assert end - start <= 40
    assert pick["start_word_index"] == 62
    assert pick["end_word_index"] == 101


def test_minimum_widens_both_sides():
    pick, transcript = pad(payoff=17.2)
    assert pick["start_word_index"] == 4
    assert pick["end_word_index"] == 24
    assert transcript.time_range(4, 24)[1] - transcript.words[4].start >= 20


def test_insufficient_candidate_keeps_tight_envelope_for_rejection():
    pick, transcript = pad(payoff=17.2, lo=10, hi=22)
    assert (pick["start_word_index"], pick["end_word_index"]) == (11, 18)
    verdict = check_story(StoryPick.model_validate(pick), transcript.time_range(11, 18),
                          transcript.words, [])
    assert verdict.status == "reject"
    assert "clean_duration_under_minimum" in verdict.reasons


@pytest.mark.parametrize("story", [None, "absent"])
def test_no_story_is_untouched(story):
    pick = {"start_word_index": 10, "end_word_index": 20, "title": "legacy"}
    if story is None:
        pick["story"] = None
    before = deepcopy(pick)
    _pad_story_picks({"clips": [pick]}, {}, Transcript())
    assert pick == before
