"""Source-time story validation and payoff survival across boundary refinement."""

from copy import deepcopy

import pytest
from autoclip.pipeline.boundaries import refine
from autoclip.pipeline.highlights import StoryPick, check_story, subtract_dark_spans
from autoclip.pipeline.prepare import Silence
from autoclip.pipeline.transcript import Transcript, Word
from pydantic import ValidationError


def words_until(end=40):
    return [Word(f"w{i}" + ("." if i % 10 == 9 else ""), i, i + 1) for i in range(end)]


def pick_data():
    return {
        "start_word_index": 0,
        "end_word_index": 34,
        "story": {
            "setup": {"start_s": 0, "end_s": 2, "text": "He approaches the cage"},
            "change": {"start_s": 15, "end_s": 16, "text": "The tiger jumps out"},
            "payoff": {"start_s": 31, "end_s": 32, "text": "He screams and runs away"},
        },
    }


def test_legacy_loads_with_warning_and_remains_usable(caplog):
    pick = StoryPick(start_word_index=0, end_word_index=34)
    assert "story_missing warning" in caplog.text
    verdict = check_story(pick, (0, 35), words_until(), [])
    assert verdict.status == "ok"
    assert "legacy" in verdict.reasons[0]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["story"].pop("setup"),
        lambda d: d["story"]["payoff"].update(end_s=30),
        lambda d: d["story"]["setup"].update(start_s=-1),
        lambda d: d["story"]["setup"].update(start_s=float("nan")),
        lambda d: d["story"]["payoff"].update(end_s=float("inf")),
        lambda d: d["story"]["change"].update(start_s=33, end_s=34),
    ],
)
def test_schema_rejects_missing_or_invalid_beats(mutation):
    data = pick_data()
    mutation(data)
    with pytest.raises(ValidationError):
        StoryPick.model_validate(data)


def test_valid_story_is_pure():
    pick = StoryPick.model_validate(pick_data())
    before = deepcopy(pick)
    verdict = check_story(pick, (0, 35), words_until(), [])
    assert verdict.status == "ok"
    assert verdict.clean_duration_s == 35
    assert pick == before


def test_cut_payoff_is_restored_within_campaign_limits():
    pick = StoryPick.model_validate(pick_data())
    verdict = check_story(pick, (0, 30), words_until(), [], max_duration_s=35)
    assert verdict.status == "widen"
    assert "payoff_outside_bounds" in verdict.reasons
    assert verdict.end_s == 33
    assert (
        check_story(
            pick, (verdict.start_s, verdict.end_s), words_until(), [], max_duration_s=35
        ).status
        == "ok"
    )


def test_payoff_in_last_second_widens():
    verdict = check_story(StoryPick.model_validate(pick_data()), (0, 32.5), words_until(), [])
    assert verdict.status == "widen"
    assert "payoff_in_last_second" in verdict.reasons
    assert verdict.end_s == 33


def test_exactly_one_second_of_tail_is_ok():
    assert (
        check_story(StoryPick.model_validate(pick_data()), (0, 33), words_until(), []).status
        == "ok"
    )


def test_impossible_widen_rejects():
    verdict = check_story(
        StoryPick.model_validate(pick_data()), (0, 30), words_until(), [], max_duration_s=32
    )
    assert verdict.status == "reject"


@pytest.mark.parametrize(
    "beat, reason",
    [
        ("setup", "setup_missing"),
        ("payoff", "payoff_text_empty_speech"),
    ],
)
def test_empty_story_text_rejects(beat, reason):
    data = pick_data()
    data["story"][beat]["text"] = "  "
    verdict = check_story(StoryPick.model_validate(data), (0, 35), words_until(), [])
    assert verdict.status == "reject"
    assert reason in verdict.reasons


def test_explicit_speech_payoff_without_transcript_still_requires_text():
    data = pick_data()
    data["story"]["payoff"].update(text="", speech_based=True)
    verdict = check_story(StoryPick.model_validate(data), (0, 35), [], [])
    assert verdict.status == "reject"
    assert "payoff_text_empty_speech" in verdict.reasons


def test_no_transcript_is_not_clean_evidence():
    verdict = check_story(StoryPick.model_validate(pick_data()), (0, 35), [], [])
    assert verdict.status == "reject"
    assert verdict.clean_duration_s == 0


def test_union_subtraction_clips_and_merges_black_spans():
    assert subtract_dark_spans(10, 40, [(0, 12), (20, 25), (23, 30), (35, 50)]) == 13


def test_silence_black_and_transcript_gap_are_not_double_counted():
    words = [w for w in words_until() if not 10 <= w.start < 20]
    verdict = check_story(
        StoryPick.model_validate(pick_data()), (0, 35), words, [Silence(10, 20)], [(15, 20)]
    )
    assert verdict.status == "ok"
    assert verdict.clean_duration_s == 25


def test_tiger_29_seconds_with_black_tail_and_925_946_transcript_gap():
    words = [Word("before.", 924, 925)] + [Word("reaction.", i, i + 1) for i in range(946, 957)]
    data = pick_data()
    data.update(start_word_index=0, end_word_index=len(words) - 1)
    data["story"] = {
        "setup": {"start_s": 928, "end_s": 930, "text": "He approaches a hidden tiger"},
        "change": {"start_s": 946, "end_s": 947, "text": "The tiger attacks"},
        "payoff": {"start_s": 947, "end_s": 948, "text": "He screams and dies"},
    }
    pick = StoryPick.model_validate(data)
    verdict = check_story(
        pick, (928, 957), words, [], [(949, 957)], min_duration_s=20, max_duration_s=60
    )
    assert verdict.status == "reject"
    assert verdict.clean_duration_s == 3
    assert "clean_duration_under_minimum" in verdict.reasons
    checks = []
    assert (
        refine(
            Transcript(words=words),
            0,
            len(words) - 1,
            pick=pick,
            dark_spans=[(949, 957)],
            on_story_check=checks.append,
        )
        is None
    )
    assert checks[0].status == "reject"


def test_refine_checks_raw_and_refined_and_restores_caption_words():
    pick = StoryPick.model_validate(pick_data())
    checks = []
    boundary = refine(
        Transcript(words=words_until()),
        0,
        34,
        pick=pick,
        min_duration_s=20,
        max_duration_s=35,
        on_story_check=checks.append,
    )
    assert [v.status for v in checks] == ["ok", "widen"]
    assert boundary is not None
    assert boundary.end_s == 33
    assert boundary.end_word == 32


def test_refine_rejects_raw_story_before_snapping():
    data = pick_data()
    data["story"]["payoff"]["text"] = ""
    checks = []
    assert (
        refine(
            Transcript(words=words_until()),
            0,
            34,
            pick=StoryPick.model_validate(data),
            on_story_check=checks.append,
        )
        is None
    )
    assert len(checks) == 1
    assert checks[0].status == "reject"


def test_refine_rejects_when_alignment_cuts_payoff_tail_at_ceiling():
    data = pick_data()
    data.update(start_word_index=5, end_word_index=34)
    # Raw 5..35 is valid; sentence snapping starts at 0 and the 30s
    # ceiling then removes a payoff that cannot be restored by widening.
    data["story"]["setup"].update(start_s=5, end_s=7)
    checks = []
    assert (
        refine(
            Transcript(words=words_until()),
            5,
            34,
            pick=StoryPick.model_validate(data),
            max_duration_s=30,
            on_story_check=checks.append,
        )
        is None
    )
    assert [v.status for v in checks] == ["ok", "reject"]
    assert "payoff_outside_bounds" in checks[-1].reasons


def test_quiet_gameplay_is_not_dead_footage():
    """A silent build-up (pause < LONG_GAP_S, plus detected silence) still counts as footage."""
    words = [w for w in words_until() if not 10 <= w.start < 14]  # 4 s with no speech
    pick = StoryPick.model_validate(pick_data())
    verdict = check_story(pick, (0, 35), words, [Silence(9.0, 15.0)], min_duration_s=30)
    assert verdict.status == "ok"
    assert verdict.clean_duration_s == 35
