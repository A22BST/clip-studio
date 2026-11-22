"""Clip boundary refinement — sentence snapping, duration clamping, silence alignment."""

from __future__ import annotations

import pytest
from autoclip.pipeline import boundaries
from autoclip.pipeline.highlights import StoryPick
from autoclip.pipeline.prepare import Silence
from autoclip.pipeline.transcript import Transcript, Word


def make_transcript(sentences: list[list[str]], *, word_duration: float = 0.5) -> Transcript:
    """Build a transcript with evenly spaced words and clean sentence boundaries."""
    words: list[Word] = []
    t = 0.0
    for sentence in sentences:
        for index, text in enumerate(sentence):
            token = text + ("." if index == len(sentence) - 1 else "")
            words.append(Word(text=token, start=t, end=t + word_duration * 0.8))
            t += word_duration
    return Transcript(words=words)


@pytest.fixture
def transcript() -> Transcript:
    # Ten sentences of ten words: 100 words, 0.5s each, 50 seconds total.
    return make_transcript([[f"w{s}{i}" for i in range(10)] for s in range(10)])


class TestSentenceSnapping:
    def test_start_snaps_to_the_first_word_of_a_sentence(self, transcript: Transcript) -> None:
        # Index 13 is mid-second-sentence; sentence starts are 0, 10, 20, ...
        assert boundaries.snap_start_to_sentence(transcript, 13) == 10

    def test_start_prefers_moving_earlier_on_a_tie(self, transcript: Transcript) -> None:
        # Index 15 is equidistant from 10 and 20; starting wide beats cutting the hook.
        assert boundaries.snap_start_to_sentence(transcript, 15) == 10

    def test_end_snaps_to_the_last_word_of_a_sentence(self, transcript: Transcript) -> None:
        assert boundaries.snap_end_to_sentence(transcript, 27) == 29

    def test_end_prefers_moving_later_on_a_tie(self, transcript: Transcript) -> None:
        # Ending on the complete thought rather than truncating it.
        assert boundaries.snap_end_to_sentence(transcript, 24) == 29

    def test_index_zero_always_starts_a_sentence(self, transcript: Transcript) -> None:
        assert boundaries.snap_start_to_sentence(transcript, 0) == 0

    def test_final_index_always_ends_a_sentence(self, transcript: Transcript) -> None:
        last = len(transcript.words) - 1
        assert boundaries.snap_end_to_sentence(transcript, last) == last

    def test_unpunctuated_transcript_leaves_the_index_alone(self) -> None:
        transcript = Transcript(
            words=[Word(text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(60)]
        )

        assert boundaries.snap_start_to_sentence(transcript, 30) == 30


class TestRefine:
    def test_produces_a_boundary_inside_the_duration_range(self, transcript: Transcript) -> None:
        result = boundaries.refine(transcript, 10, 69, min_duration_s=20.0, max_duration_s=90.0)

        assert result is not None
        assert 20.0 <= result.duration_s <= 90.0
        assert result.start_word == 10

    def test_over_long_range_is_trimmed_to_a_sentence_end(self, transcript: Transcript) -> None:
        # Words 0-99 span 50s; ask for a 10s ceiling.
        result = boundaries.refine(transcript, 0, 99, min_duration_s=5.0, max_duration_s=10.0)

        assert result is not None
        assert result.duration_s <= 10.0
        assert transcript.words[result.end_word].ends_sentence

    def test_too_short_range_is_extended(self, transcript: Transcript) -> None:
        # Words 0-9 span 5s; require at least 12s.
        result = boundaries.refine(transcript, 0, 9, min_duration_s=12.0, max_duration_s=40.0)

        assert result is not None
        assert result.duration_s >= 12.0

    def test_returns_none_when_no_valid_length_exists(self, transcript: Transcript) -> None:
        # The whole transcript is 50s; a 200s floor cannot be met.
        assert (
            boundaries.refine(transcript, 0, 99, min_duration_s=200.0, max_duration_s=300.0) is None
        )

    def test_inverted_range_is_rejected(self, transcript: Transcript) -> None:
        assert boundaries.refine(transcript, 50, 50) is None

    def test_out_of_range_indices_are_clamped(self, transcript: Transcript) -> None:
        result = boundaries.refine(transcript, -5, 9_999, min_duration_s=5.0, max_duration_s=90.0)

        assert result is not None
        assert 0 <= result.start_word < len(transcript.words)
        assert 0 <= result.end_word < len(transcript.words)

    def test_empty_transcript_returns_none(self) -> None:
        assert boundaries.refine(Transcript(), 0, 10) is None

    def test_start_never_goes_negative(self, transcript: Transcript) -> None:
        result = boundaries.refine(transcript, 0, 59, min_duration_s=5.0, max_duration_s=90.0)

        assert result is not None
        assert result.start_s >= 0.0


class TestSilenceAlignment:
    def test_start_lands_inside_a_nearby_silence(self) -> None:
        # Speech begins at 10.0; silence runs 9.4-10.0.
        silences = [Silence(start=9.4, end=10.0)]

        aligned = boundaries.align_start(10.0, silences)

        assert 9.4 < aligned < 10.0
        assert aligned == pytest.approx(10.0 - boundaries.SILENCE_LEAD_S)

    def test_start_never_precedes_the_silence(self) -> None:
        # A very short silence must not be overrun by the lead-in.
        silences = [Silence(start=9.95, end=10.0)]

        aligned = boundaries.align_start(10.0, silences)

        assert aligned >= 9.95

    def test_end_lands_inside_the_following_silence(self) -> None:
        silences = [Silence(start=30.0, end=31.0)]

        aligned = boundaries.align_end(30.0, silences)

        assert 30.0 <= aligned < 31.0
        assert aligned == pytest.approx(30.0 + boundaries.SILENCE_TAIL_S)

    def test_end_never_overruns_the_silence(self) -> None:
        silences = [Silence(start=30.0, end=30.1)]

        aligned = boundaries.align_end(30.0, silences)

        assert aligned <= 30.1

    def test_falls_back_to_fixed_padding_without_silences(self) -> None:
        assert boundaries.align_start(10.0, []) == pytest.approx(10.0 - boundaries.FALLBACK_LEAD_S)
        assert boundaries.align_end(30.0, []) == pytest.approx(30.0 + boundaries.FALLBACK_TAIL_S)

    def test_distant_silences_are_ignored(self) -> None:
        # A silence five seconds away says nothing about this boundary.
        silences = [Silence(start=2.0, end=5.0)]

        assert boundaries.align_start(10.0, silences) == pytest.approx(
            10.0 - boundaries.FALLBACK_LEAD_S
        )

    def test_alignment_only_ever_widens_a_clip(self) -> None:
        silences = [Silence(start=9.0, end=10.0), Silence(start=30.0, end=31.0)]

        start = boundaries.align_start(10.0, silences)
        end = boundaries.align_end(30.0, silences)

        assert start <= 10.0
        assert end >= 30.0

    def test_refine_respects_the_ceiling_after_alignment(self, transcript: Transcript) -> None:
        # Generous silences either side would push the clip over the limit.
        silences = [Silence(start=0.0, end=5.0), Silence(start=20.0, end=26.0)]

        result = boundaries.refine(
            transcript, 10, 39, silences=silences, min_duration_s=5.0, max_duration_s=12.0
        )

        assert result is not None
        assert result.duration_s <= 12.0


def story_pick(start=5, payoff_end=29.8):
    return StoryPick(
        start_word_index=0,
        end_word_index=30,
        story={
            "setup": {"start_s": start, "end_s": start + 2, "text": "A strange object"},
            "change": {"start_s": 20, "end_s": 22, "text": "It moves"},
            "payoff": {"start_s": 28, "end_s": payoff_end, "text": "He screams"},
        },
    )


@pytest.mark.parametrize(
    "cut_kind, expected_end", [("sentence", 33), ("silence", 31.28), ("word", 31)]
)
def test_story_restores_payoff_tail_and_caption_words(cut_kind, expected_end):
    words = [Word(f"w{i}", i, i + 1) for i in range(50)]
    words[29].text += "."
    if cut_kind == "sentence":
        words[32].text += "."
    silences = [Silence(31, 32)] if cut_kind == "silence" else []
    # The raw range has a valid tail, but sentence snapping ends at 30.
    result = boundaries.refine(
        Transcript(words=words), 0, 30, pick=story_pick(), silences=silences
    )
    assert result is not None
    assert result.end_s == pytest.approx(expected_end)
    assert result.end_s - 29.8 >= 1
    covered = [i for i, w in enumerate(words) if w.start < result.end_s and w.end > result.start_s]
    assert (result.start_word, result.end_word) == (covered[0], covered[-1])


def test_story_raw_tail_only_failure_can_be_repaired():
    words = [Word(f"w{i}" + ("." if i == 29 else ""), i, i + 1) for i in range(50)]
    pick = story_pick()
    pick.end_word_index = 29
    result = boundaries.refine(Transcript(words=words), 0, 29, pick=pick)
    assert result is not None
    assert result.end_s - pick.story.payoff.end_s >= 1


def test_story_cap_trims_head_and_keeps_setup_lead():
    words = [Word(f"w{i}" + ("." if i in (29, 31) else ""), i, i + 1) for i in range(50)]
    pick = story_pick()
    pick.start_word_index = 5
    result = boundaries.refine(
        Transcript(words=words), 5, 30, pick=pick, max_duration_s=28
    )
    assert result is not None
    assert result.start_s == 4
    assert result.end_s == 32
    assert result.duration_s == 28
    assert result.start_s <= pick.story.setup.start_s - 0.5
    assert result.start_word == 4


def test_story_start_snap_preserves_setup_lead():
    words = [Word(f"w{i}" + ("." if i in (9, 29, 31) else ""), i, i + 1) for i in range(50)]
    pick = story_pick(start=9)
    pick.start_word_index = 7
    result = boundaries.refine(Transcript(words=words), 7, 30, pick=pick)
    assert result is not None
    assert result.start_s == 8.5
    assert result.start_word == 8


def test_story_tail_cannot_extend_past_transcript():
    words = [Word(f"w{i}" + ("." if i == 29 else ""), i, i + 1) for i in range(30)]
    pick = story_pick()
    pick.end_word_index = 29
    assert boundaries.refine(Transcript(words=words), 0, 29, pick=pick) is None


def test_story_rejects_when_cap_cannot_preserve_setup_and_payoff_tail():
    words = [Word(f"w{i}" + ("." if i == 29 else ""), i, i + 1) for i in range(50)]
    pick = story_pick(start=0)
    pick.end_word_index = 29
    assert boundaries.refine(
        Transcript(words=words), 0, 29, pick=pick, max_duration_s=30
    ) is None


@pytest.mark.parametrize("legacy_pick", [None, StoryPick(start_word_index=10, end_word_index=69)])
def test_no_story_preserves_existing_bounds(transcript, legacy_pick):
    result = boundaries.refine(transcript, 10, 69, pick=legacy_pick)
    assert result == boundaries.Boundary(start_s=4.75, end_s=35.25, start_word=10, end_word=69)
