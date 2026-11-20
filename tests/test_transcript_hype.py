import pytest
from autoclip.pipeline.transcript import Transcript, Word
from autoclip.pipeline.transcript_hype import (
    TranscriptHypeConfig,
    compute_transcript_hype,
)


def _speech(duration_s: float, wps: float = 2.5) -> list[Word]:
    words, t, step = [], 0.0, 1.0 / wps
    pool = ["so", "I", "think", "we", "should", "go", "check", "the", "house", "first", "okay"]
    i = 0
    while t < duration_s:
        words.append(Word(pool[i % len(pool)], t, t + step * 0.8))
        t += step
        i += 1
    return words


def _insert(words: list[Word], at: float, phrase: list[str]) -> list[Word]:
    kept = [w for w in words if not at <= w.start < at + len(phrase) * 0.3]
    extra = [Word(p, at + 0.3 * i, at + 0.3 * i + 0.25) for i, p in enumerate(phrase)]
    return sorted(kept + extra, key=lambda w: w.start)


def test_excited_burst_is_top_peak():
    words = _speech(900)
    words = _insert(words, 400, ["oh", "my", "god", "no", "no", "no", "no", "way", "let's", "go"])
    peaks = compute_transcript_hype(Transcript(words=words), duration_s=900)
    assert peaks
    top = peaks[0]
    assert top.window_start - 1 <= 400 <= top.window_end + 1
    assert any("oh my god" in r or "repeated" in r for r in top.reasons)
    assert top.window_end - top.window_start <= 150


def test_laughter_and_questions_count():
    words = _speech(900)
    words = _insert(words, 200, ["ha", "ha", "ha", "hahaha", "lol"])
    words = _insert(words, 600, ["what?", "what?", "what?", "huh?"])
    peaks = compute_transcript_hype(Transcript(words=words), duration_s=900, top_n=5)
    times = [p.t for p in peaks]
    assert any(abs(t - 202) < 30 for t in times)
    assert any(abs(t - 601) < 30 for t in times)


def test_flat_speech_yields_nothing_or_weak():
    peaks = compute_transcript_hype(Transcript(words=_speech(600)), duration_s=600)
    assert peaks == []


def test_empty_and_zero_top_n():
    assert compute_transcript_hype(Transcript()) == []
    assert compute_transcript_hype(Transcript(words=_speech(60)), top_n=0) == []


def test_deterministic_and_respects_top_n():
    words = _speech(1800)
    for at in (200, 700, 1200, 1600):
        words = _insert(words, at, ["holy", "no", "way", "oh", "my", "god"])
    a = compute_transcript_hype(Transcript(words=words), duration_s=1800, top_n=3)
    b = compute_transcript_hype(Transcript(words=words), duration_s=1800, top_n=3)
    assert a == b and len(a) == 3
    assert all(p.window_end <= 1800 for p in a)


def test_config_validation():
    with pytest.raises(ValueError):
        TranscriptHypeConfig(bin_s=0)
    with pytest.raises(ValueError):
        TranscriptHypeConfig(w_rate=float("nan"))
    with pytest.raises(ValueError):
        TranscriptHypeConfig(top_n=-1)
