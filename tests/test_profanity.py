"""Check caption preservation and run the generated audio filter through ffmpeg."""

from __future__ import annotations

import shutil
import subprocess

import pytest
from autoclip.pipeline.profanity import bleep_audio_filter, censor_words, profane_intervals
from autoclip.pipeline.transcript import Word


@pytest.mark.parametrize("mode", ["mask", "bleep"])
@pytest.mark.parametrize(
    "text,expected",
    [
        ("FUCK!", "F***!"),
        ("sh1t,", "s***,"),
        ("f*cking", "f******"),
        ("bitches", "b******"),
        ("fucked", "f*****"),
        ("$hit", "$***"),
        ("(Shit.)", "(S***.)"),
        ("f.u.c.k", "f.*.*.*"),
        ("shitting", "s*******"),
        ("crapped", "c******"),
    ],
)
def test_mask(mode: str, text: str, expected: str) -> None:
    original = Word(text, 1, 2, "speaker")
    edited = censor_words([original], mode)[0]
    assert edited == Word(expected, 1, 2, "speaker")
    assert original.text == text


def test_innocent_words_and_off() -> None:
    words = [Word(t, 0, 1) for t in ["assistant", "class", "Scunthorpe", "cocktail", "hello"]]
    assert censor_words(words, "mask") == words
    assert censor_words(words, "off") is words
    with pytest.raises(ValueError, match="Unknown"):
        censor_words(words, "unknown")


def test_intervals_merge_and_clamp() -> None:
    words = [Word("shit", 0, 0.2), Word("fuck", 0.25, 0.5), Word("hello", 1, 2)]
    assert profane_intervals(words) == [(0, 0.55)]
    assert profane_intervals(censor_words(words, "mask")) == [(0, 0.55)]
    assert profane_intervals([]) == []
    assert bleep_audio_filter([]) == ""
    with pytest.raises(ValueError):
        profane_intervals(words, pad_s=-1)
    with pytest.raises(ValueError):
        bleep_audio_filter([(2, 1)])


def test_real_ffmpeg_filter() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg missing")
    filters = bleep_audio_filter([(0.1, 0.3), (0.6, 0.8)])
    assert "between(t,0.100000,0.300000)" in filters
    result = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-af",
            filters,
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
