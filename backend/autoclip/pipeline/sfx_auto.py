"""Conservative story-based effects, payoff onsets and word-gap placement."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

from . import ffmpeg, sfx
from .sfx_catalog import CATALOG, COMEDIC, KEYWORDS, SERIOUS


def _matches(text, phrases):
    return sum(bool(re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", text, re.I)) for p in phrases)


def context_text(story=None, hook="", title="", fallback=""):
    beats = story.model_dump() if hasattr(story, "model_dump") else story or {}
    text = " ".join(str((beats.get(key) or {}).get("text", "")) for key in ("change", "payoff"))
    return " ".join((text, hook or "", title or "", fallback if not text.strip() else "")).lower()


def choose_category(text: str) -> str | None:
    """Require an explicit signal; generic reactions alone do not justify an effect."""
    if _matches(text, SERIOUS):
        return None
    scores = {cat: _matches(text, words) for cat, words in KEYWORDS.items()}
    # A physical payoff outweighs chat discussing it; chat outweighs giveaway money.
    if scores["IMPACT"]:
        return "IMPACT"
    if scores["REVEAL"]:
        return "REVEAL"
    if scores["NOTIFICATION"]:
        return "NOTIFICATION"
    winner = max(scores, key=scores.get)
    return winner if scores[winner] else None


def _words(transcript):
    return transcript.words if hasattr(transcript, "words") else transcript or []


def overlaps_speech(at_s, words, start_s=0):
    """A start is unsafe if speech occupies any of its preceding 400 ms."""
    at = at_s + start_s
    return any(w.start <= at and w.end > at - .4 + 1e-7 for w in words)


def _safe_time(at, rise, words, start_s, duration):
    if not 3 <= at <= duration - 1.5:
        return None
    if rise >= 10 or not overlaps_speech(at, words, start_s):
        return at
    for candidate in sorted({w.end - start_s + .4 for w in words}):
        if at <= candidate <= min(at + 1, duration - 1.5) and not overlaps_speech(candidate, words, start_s):
            return candidate
    return None


def loudness_onsets(audio_path, start_s, end_s):
    command = [ffmpeg.ffmpeg_path(), "-v", "error", "-ss", str(start_s),
               "-i", str(audio_path), "-t", str(end_s - start_s), "-vn",
               "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise ffmpeg.FFmpegError("Could not decode SFX analysis window", command=command,
                                 stderr=result.stderr.decode("utf-8", errors="replace"))
    samples = np.frombuffer(result.stdout, dtype="<f4")
    count = len(samples) // 800
    frames = samples[:count * 800].reshape(count, 800).astype(np.float64)
    db = 10 * np.log10(np.maximum(np.mean(frames * frames, axis=1), 1e-12))
    rise = np.zeros(count)
    for i in range(30, count):
        rise[i] = db[i] - np.median(db[i - 30:i])
    peaks = {}
    for i in range(30, count):
        if rise[i] < 6:
            continue
        onset = i
        while onset > 30 and rise[onset - 1] >= 6:
            onset -= 1
        peaks[onset * .05] = max(peaks.get(onset * .05, 0), float(rise[i]))
    return list(peaks.items())


def _ledger_path():
    return sfx.library_dir() / "recent.json"


def recent_names():
    try:
        value = json.loads(_ledger_path().read_text(encoding="utf-8"))
        return [name for name in value if isinstance(name, str)][-6:] if isinstance(value, list) else []
    except (FileNotFoundError, ValueError):
        return []


def remember(name):
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement prevents an interrupted write leaving invalid JSON.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps((recent_names() + [name])[-6:]), encoding="utf-8")
    temporary.replace(path)


def _allowed(name, category, text, kind):
    entry = CATALOG.get(name)
    if not entry or not category:
        return False
    if entry[0] == "BUILD-UP":
        return kind == "riser"
    if kind == "riser" or entry[0] != category:
        return False
    return name != "MEME BOOM" or (
        bool(_matches(text, COMEDIC)) and bool(_matches(text, ("fail", "failed", "oops", "blunder", "oh no")))
    )


def _canonical(name):
    return next((n for n in CATALOG if n.casefold() == Path(name).stem.casefold()), None)


def suggest_events(audio_path_or_wav: str | Path, start_s: float, end_s: float, seed: str,
                   *, story=None, hook="", title="", transcript=None, record=True) -> list[dict]:
    """Source-based story/words in; one clip-relative event out. Seed is legacy API only.

    With no story timing, use transcript around the strongest eligible onset.
    Preview callers set record=False so the ledger remains untouched.
    """
    if not all(math.isfinite(t) for t in (start_s, end_s)) or start_s < 0 or end_s <= start_s:
        raise ValueError("Expected a finite positive source window")
    if transcript is None:
        return []  # Cannot prove speech safety without word timestamps.
    duration = end_s - start_s
    words = _words(transcript)
    beats = story.model_dump() if hasattr(story, "model_dump") else story or {}
    payoff = beats.get("payoff") or {}
    peaks = [(at, rise) for at, rise in loudness_onsets(audio_path_or_wav, start_s, end_s)
             if 3 <= at <= duration - 1.5]
    anchor = payoff.get("start_s")
    if anchor is not None:
        anchor -= start_s
        nearby = [(at, rise) for at, rise in peaks if abs(at - anchor) <= 1.5]
        at, rise = max(nearby, key=lambda p: (p[1], -abs(p[0] - anchor))) if nearby else (anchor, 0)
    elif peaks:
        at, rise = max(peaks, key=lambda p: (p[1], -p[0]))
    else:
        return []
    fallback_end = payoff.get("end_s", start_s + at + 1.5)
    fallback = " ".join(w.text for w in words if w.end >= start_s + at - 1.5 and w.start <= fallback_end)
    text = context_text(story, hook, title, fallback)
    category = choose_category(text)
    at = _safe_time(at, rise, words, start_s, duration)
    if not category or at is None:
        return []
    available = {_canonical(n): n for n in sfx.available_names()}
    history = recent_names()
    candidates = [n for n in CATALOG if n in available and _allowed(n, category, text, "impact")
                  and (not history or n.casefold() != history[-1].casefold())]
    if not candidates:
        return []
    # Least recently used within the category; Pop is the default small accent.
    name = min(candidates, key=lambda n: (max(i + 1 for i, used in enumerate(history) if used == n) if n in history else 0,
                                         n != "Pop" if category == "SPOTLIGHT" else False))
    if record:
        remember(name)
    return [{"name": available[name], "at_s": round(at, 4), "gain_db": sfx.DEFAULT_GAIN_DB, "kind": "impact"}]


def validate_events(events, audio_path, start_s, end_s, *, story=None, hook="", title="", transcript=None,
                    record=True):
    """Drop invalid model picks with reasons; never replace a rejected manual choice."""
    if not events:
        return [], []
    try:
        if len(events) != 1:
            raise ValueError("one effect per clip required")
        event = sfx.SFXEvent.model_validate(events[0])
        name = _canonical(event.name)
        words = _words(transcript)
        beats = story.model_dump() if hasattr(story, "model_dump") else story or {}
        payoff = beats.get("payoff") or {}
        a = payoff.get("start_s", start_s + event.at_s - 1.5)
        b = payoff.get("end_s", start_s + event.at_s + 1.5)
        fallback = " ".join(w.text for w in words if w.end >= a and w.start <= b)
        text = context_text(story, hook, title, fallback)
        if not _allowed(name, choose_category(text), text, event.kind):
            raise ValueError("category mismatch or riser used as impact")
        if event.kind == "riser" and not payoff:
            raise ValueError("riser needs a timed story payoff to align its end")
        if not 3 <= event.at_s <= end_s - start_s - 1.5:
            raise ValueError("event outside payoff-safe clip boundaries")
        if payoff and not payoff["start_s"] - start_s - 1.5 <= event.at_s <= payoff["start_s"] - start_s + 2.5:
            raise ValueError("event is not near the story payoff")
        actual_start = event.at_s
        if event.kind == "riser":
            actual_start -= ffmpeg.probe(sfx.resolve_name(event.name)).duration_s
        if actual_start < 3:
            raise ValueError("effect starts in the first 3 seconds")
        if transcript is None:
            raise ValueError("speech safety unavailable")
        if overlaps_speech(actual_start, words, start_s):
            peaks = loudness_onsets(audio_path, start_s, end_s)
            if not any(abs(at - actual_start) <= .05 and rise >= 10 for at, rise in peaks):
                raise ValueError("effect starts over speech")
        history = recent_names()
        if history and name.casefold() == history[-1].casefold():
            raise ValueError("effect repeats the previous selection")
        sfx.resolve_name(event.name)
        if record:
            remember(name)
        return events, []
    except (ValueError, TypeError, OSError, ffmpeg.FFmpegError) as exc:
        return [], [f"sfx warning: {exc}; rendering without sfx"]
