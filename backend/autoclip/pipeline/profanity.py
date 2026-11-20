"""Use whole-token matching so innocent embedded syllables stay readable."""

from __future__ import annotations

import math
import re
from dataclasses import replace

from .transcript import Word

PROFANE_WORDS = frozenset(
    {
        "fuck",
        "shit",
        "bitch",
        "ass",
        "asshole",
        "bastard",
        "damn",
        "crap",
        "piss",
        "dick",
        "cock",
        "cunt",
        "motherfucker",
        "bullshit",
    }
)
_LEET = str.maketrans(
    {"0": "o", "1": "i", "!": "i", "3": "e", "4": "a", "@": "a", "5": "s", "$": "s", "7": "t"}
)
_TOKEN = re.compile(r"[\w@$*!]+(?:[.'-][\w@$*!]+)*", re.UNICODE)
_SUFFIXES = ("", "s", "es", "ing", "ed", "er", "ers", "y", "'s")
_DOUBLED_STEMS = {"shit", "bullshit", "crap"}


def _profane(token: str) -> bool:
    normalized = token.casefold().translate(_LEET).replace(".", "").replace("-", "")
    for base in PROFANE_WORDS:
        for suffix in _SUFFIXES:
            stem = base + base[-1] if base in _DOUBLED_STEMS and suffix in {"ing", "ed"} else base
            target = stem + suffix
            if (
                len(normalized) == len(target)
                and all(
                    char == expected or char == "*"
                    for char, expected in zip(normalized, target, strict=True)
                )
                and any(char.isalpha() for char in normalized)
            ):
                return True
    return False


def _mask_text(text: str) -> str:
    def mask(match: re.Match[str]) -> str:
        token = match.group()
        # Exclamation marks at the end are punctuation, not leetspeak letters.
        core = token.rstrip("!")
        if not _profane(core):
            return token
        masked = core[:1] + "".join(
            "*" if char.isalnum() or char in "@$*!" else char for char in core[1:]
        )
        return masked + token[len(core) :]

    return _TOKEN.sub(mask, text)


def censor_words(words: list[Word], mode: str) -> list[Word]:
    """Copy edited words so caption filtering never mutates the source transcript."""
    if mode == "off":
        return words
    if mode not in {"mask", "bleep"}:
        raise ValueError(f"Unknown swear filter mode {mode!r}; expected off, mask or bleep")
    return [replace(word, text=_mask_text(word.text)) for word in words]


def profane_intervals(words: list[Word], *, pad_s: float = 0.05) -> list[tuple[float, float]]:
    """Merge padded words so adjacent swears do not leave audible gaps."""
    if not math.isfinite(pad_s) or pad_s < 0:
        raise ValueError("pad_s must be finite and nonnegative")
    intervals = []
    for word in words:
        if _mask_text(word.text) != word.text or any(
            _profane(m.group().rstrip("!")) for m in _TOKEN.finditer(word.text)
        ):
            intervals.append((max(0, word.start - pad_s), word.end + pad_s))
    return _merge(intervals)


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise ValueError("Intervals must have finite 0 <= start <= end")
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def bleep_audio_filter(intervals: list[tuple[float, float]], *, tone_hz: int = 1000) -> str:
    """Mute swears in a plain -af chain; a mixed sine needs a separate filter graph.

    ``tone_hz`` is reserved for a future graph-based tone implementation.
    """
    if tone_hz <= 0:
        raise ValueError("tone_hz must be positive")
    return ",".join(
        f"volume=enable='between(t,{start:.6f},{end:.6f})':volume=0"
        for start, end in _merge(intervals)
    )
