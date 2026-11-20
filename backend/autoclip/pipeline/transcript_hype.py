"""Streamer-excitement candidates from the whole transcript, independent of chat and audio.

Whisper output is nearly punctuation-free (few "!"), so the cheap features lean on words:
an excitement lexicon, repeated words ("no no no"), laughter tokens, question bursts and
a speech-rate spike against a rolling baseline. The result is a *candidate generator*: a
Claude ranking step (docs/hype-fusion-protocol.md) picks the final windows.

All defaults are frozen by the pre-registered fusion protocol; change them only as a
separately reported exploratory experiment.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .hype import _baseline
from .transcript import Transcript

# Phrase -> weight. Matched on lower-cased tokens with punctuation stripped, so "Let's go!"
# and "lets go" both match. Single generic reaction words get small weights.
LEXICON: dict[tuple[str, ...], float] = {
    ("no", "way"): 2.0,
    ("oh", "my", "god"): 2.5,
    ("oh", "my", "gosh"): 2.0,
    ("oh", "my"): 1.0,
    ("omg",): 2.0,
    ("let's", "go"): 2.0,
    ("lets", "go"): 2.0,
    ("let's", "goo"): 2.0,
    ("holy",): 1.5,
    ("what", "the"): 1.5,
    ("are", "you", "kidding"): 2.0,
    ("you", "serious"): 1.5,
    ("i", "can't", "believe"): 2.0,
    ("i'm", "dying"): 2.0,
    ("i'm", "dead"): 2.0,
    ("oh", "no"): 1.0,
    ("oh", "shit"): 2.0,
    ("wtf",): 2.0,
    ("yo",): 0.8,
    ("yooo",): 1.5,
    ("wow",): 1.0,
    ("damn",): 1.0,
    ("dude",): 0.5,
    ("bro",): 0.5,
    ("insane",): 1.0,
    ("crazy",): 1.0,
    ("wait",): 0.6,
    ("stop",): 0.4,
    ("fuck",): 1.2,
    ("fucking",): 1.0,
    ("shit",): 1.0,
    ("oh", "my", "lord"): 2.0,
    ("jesus",): 1.0,
    ("no",): 0.2,
}
_MAX_NGRAM = max(len(p) for p in LEXICON)
_EMPHATIC = frozenset({"no", "oh", "wait", "what", "yo", "stop", "yes", "yeah", "come", "go"})
_LAUGH = re.compile(r"^(?:h?a(?:h?a)+h?|he(?:he)+h?|lol|lmao|lmfao|rofl|laugh(?:s|ing|ter)?)$")
_STRIP = re.compile(r"^[^\w']+|[^\w']+$")


@dataclass
class TranscriptHypeConfig:
    """Frozen defaults (pre-registered, not tuned on any viewer-clip data)."""

    bin_s: float = 10.0
    rolling_window_s: float = 300.0
    pre_s: float = 30.0
    post_s: float = 10.0
    merge_gap_s: float = 60.0
    max_window_s: float = 150.0
    top_n: int = 15
    min_score: float = 2.0
    w_lexicon: float = 1.0
    lexicon_cap: float = 6.0
    w_repeat: float = 1.0
    repeat_cap: float = 4.0
    w_laugh: float = 1.0
    laugh_cap: float = 4.0
    w_question: float = 0.5
    question_cap: float = 4.0
    w_exclaim: float = 0.7
    exclaim_cap: float = 4.0
    w_rate: float = 0.8

    def __post_init__(self) -> None:
        for name in ("bin_s", "rolling_window_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name, value in vars(self).items():
            if name == "top_n":
                if not isinstance(value, int) or value < 0:
                    raise ValueError("top_n must be a nonnegative integer")
            elif not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")


@dataclass
class TranscriptPeak:
    """Same shape as ``HypePeak`` so the three candidate sources can be pooled."""

    t: float
    score: float
    window_start: float
    window_end: float
    reasons: list[str]
    sample_messages: list[str] = field(default_factory=list)


def _token(text: str) -> str:
    return _STRIP.sub("", text.lower().replace("’", "'"))


@dataclass
class _Bin:
    words: int = 0
    lexicon: float = 0.0
    repeats: float = 0.0
    laughs: int = 0
    questions: int = 0
    exclaims: int = 0
    phrases: dict[str, int] = field(default_factory=dict)


def _bin_features(transcript: Transcript, cfg: TranscriptHypeConfig, size: int) -> list[_Bin]:
    bins = [_Bin() for _ in range(size)]
    words = transcript.words
    tokens = [_token(w.text) for w in words]
    index = lambda t: min(size - 1, max(0, int(t / cfg.bin_s)))  # noqa: E731
    i = 0
    while i < len(words):
        b = bins[index(words[i].start)]
        b.words += 1
        raw = words[i].text
        b.questions += raw.count("?")
        b.exclaims += raw.count("!")
        tok = tokens[i]
        if tok and _LAUGH.match(tok):
            b.laughs += 1
        # Longest lexicon phrase starting here wins; it consumes its tokens for the weight only.
        for n in range(min(_MAX_NGRAM, len(words) - i), 0, -1):
            phrase = tuple(tokens[i : i + n])
            weight = LEXICON.get(phrase)
            if weight is not None:
                b.lexicon += weight
                label = " ".join(phrase)
                b.phrases[label] = b.phrases.get(label, 0) + 1
                break
        # Repetition: the third occurrence of a run scores 1, further ones 0.5 each; emphatic
        # words already score on their second occurrence (0.5).
        if tok and i and tokens[i - 1] == tok:
            run = 2
            j = i - 2
            while j >= 0 and tokens[j] == tok:
                run += 1
                j -= 1
            if run >= 3:
                b.repeats += 1.0 if run == 3 else 0.5
            elif tok in _EMPHATIC:
                b.repeats += 0.5
        i += 1
    return bins


def compute_transcript_hype(
    transcript: Transcript,
    *,
    duration_s: float | None = None,
    config: TranscriptHypeConfig | None = None,
    top_n: int | None = None,
) -> list[TranscriptPeak]:
    """Rank moments where the streamer's own words look excited (no chat, no audio)."""
    cfg = config or TranscriptHypeConfig()
    limit = cfg.top_n if top_n is None else top_n
    if not transcript.words or limit <= 0:
        return []
    end_t = duration_s if duration_s is not None else transcript.words[-1].end
    if not math.isfinite(end_t) or end_t <= 0:
        raise ValueError("duration_s must be finite and positive")
    size = max(1, math.ceil(end_t / cfg.bin_s))
    bins = _bin_features(transcript, cfg, size)
    window = max(1, math.ceil(cfg.rolling_window_s / cfg.bin_s))
    rate_z, _ = _baseline([float(b.words) for b in bins], window, floor=2.0, poisson=True)

    scores: list[float] = []
    reasons: list[list[str]] = []
    for i, b in enumerate(bins):
        parts = {
            "lex": cfg.w_lexicon * min(b.lexicon, cfg.lexicon_cap),
            "repeat": cfg.w_repeat * min(b.repeats, cfg.repeat_cap),
            "laugh": cfg.w_laugh * min(b.laughs, cfg.laugh_cap),
            "question": cfg.w_question * min(max(0, b.questions - 1), cfg.question_cap),
            "exclaim": cfg.w_exclaim * min(b.exclaims, cfg.exclaim_cap),
            "rate": cfg.w_rate * min(rate_z[i], 4.0),
        }
        scores.append(sum(parts.values()))
        why = [f"{label} x{n}" for label, n in sorted(b.phrases.items(), key=lambda kv: -kv[1])[:3]]
        if parts["repeat"]:
            why.append("repeated words")
        if b.laughs:
            why.append(f"laughter x{b.laughs}")
        if b.questions > 1:
            why.append(f"{b.questions} questions")
        if b.exclaims:
            why.append(f"{b.exclaims} exclamations")
        if rate_z[i] > 1:
            why.append(f"speech rate +{rate_z[i]:.1f} sd")
        reasons.append(why)

    # Smooth over neighbours so one excited sentence split across a bin edge scores once.
    smooth = [
        scores[i]
        + 0.5 * (scores[i - 1] if i else 0.0)
        + 0.5 * (scores[i + 1] if i + 1 < size else 0.0)
        for i in range(size)
    ]
    candidates: list[TranscriptPeak] = []
    for i, score in enumerate(smooth):
        if score < cfg.min_score:
            continue
        if i and score <= smooth[i - 1]:
            continue
        if i + 1 < size and score < smooth[i + 1]:
            continue
        t = min((i + 0.5) * cfg.bin_s, end_t)
        candidates.append(
            TranscriptPeak(
                t, score, max(0.0, t - cfg.pre_s), min(t + cfg.post_s, end_t), reasons[i]
            )
        )

    merged: list[TranscriptPeak] = []
    for peak in candidates:
        if (
            merged
            and peak.window_start - merged[-1].window_end < cfg.merge_gap_s
            and max(merged[-1].window_end, peak.window_end) - merged[-1].window_start
            <= cfg.max_window_s
        ):
            prev = merged[-1]
            best = peak if peak.score > prev.score else prev
            merged[-1] = TranscriptPeak(
                best.t,
                best.score,
                prev.window_start,
                max(prev.window_end, peak.window_end),
                best.reasons,
            )
        else:
            merged.append(peak)
    return sorted(merged, key=lambda p: (-p.score, p.t))[:limit]
