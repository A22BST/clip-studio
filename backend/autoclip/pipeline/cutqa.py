"""Cut-point QA: no clip may start or end mid-word.

Idea from clipper-skill (MIT, RealAdii): after rendering, re-transcribe the first and
last few seconds of the finished clip and compare what is heard with the words the
cut was supposed to contain. A clip that opens on "...ow way" instead of "no way"
sounds broken even when the captions look right.

The comparison (:func:`compare_edge`) is pure so it is unit-testable; the audio
extraction + Whisper call (:func:`check_clip_edges`) wraps it.
"""

from __future__ import annotations

import difflib
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..config import WhisperSettings
from . import ffmpeg, transcribe

log = logging.getLogger(__name__)

EDGE_S = 5.0
#: Similarity above which two words count as the same (Whisper misspells and hyphenates).
MATCH_RATIO = 0.7

Edge = Literal["start", "end"]


@dataclass
class CutIssue:
    edge: Edge
    severity: Literal["error", "warning"]
    message: str
    expected: list[str]
    heard: list[str]


def _norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def _same(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= MATCH_RATIO


def compare_edge(expected: list[str], heard: list[str], edge: Edge) -> CutIssue | None:
    """Compare the words a clip edge should have with the words actually heard.

    ``expected`` and ``heard`` are in playback order. For the start edge the first
    heard word must be the first expected word; for the end edge the last heard word
    must be the last expected word. If instead it matches the *neighbouring* expected
    word, the cut swallowed a word -> error. No match at all is only a warning
    (Whisper noise on music or game audio is common).
    """
    expected = [w for w in expected if _norm(w)]
    heard = [w for w in heard if _norm(w)]
    if not expected:
        return None
    if not heard:
        # Silence at the edge is a clean cut; nothing was spoken there.
        return None

    if edge == "start":
        probe, want, next_want = heard[0], expected[0], expected[1] if len(expected) > 1 else ""
    else:
        probe, want, next_want = heard[-1], expected[-1], expected[-2] if len(expected) > 1 else ""

    if _same(probe, want):
        return None
    if next_want and _same(probe, next_want):
        side = "first" if edge == "start" else "last"
        return CutIssue(
            edge, "error", f"the {side} word {want!r} is cut off (heard {probe!r} first)",
            expected, heard,
        )
    return CutIssue(
        edge, "warning", f"heard {probe!r}, expected {want!r}: could not confirm the cut",
        expected, heard,
    )


def _edge_wav(clip: Path, edge: Edge, dest: Path) -> None:
    seek = ["-t", str(EDGE_S)] if edge == "start" else ["-sseof", str(-EDGE_S)]
    cmd = [
        ffmpeg.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", *seek,
        "-i", str(clip), "-vn", "-ac", "1", "-ar", "16000", str(dest),
    ]  # fmt: skip
    subprocess.run(cmd, check=True, capture_output=True)


def check_clip_edges(
    clip: Path,
    first_words: list[str],
    last_words: list[str],
    *,
    whisper: WhisperSettings | None = None,
) -> list[CutIssue]:
    """Re-transcribe the first/last 5 s of a rendered clip and flag cut-off words.

    ``first_words`` / ``last_words`` are the first/last few words the clip should have
    (from the source transcript, in order).
    """
    whisper = whisper or WhisperSettings(model="small", language="en")
    issues: list[CutIssue] = []
    with tempfile.TemporaryDirectory() as tmp:
        for edge, expected in (("start", first_words[:4]), ("end", last_words[-4:])):
            wav = Path(tmp) / f"{edge}.wav"
            try:
                _edge_wav(clip, edge, wav)  # type: ignore[arg-type]
                heard = [w.text for w in transcribe.transcribe(wav, whisper).words]
            except Exception as exc:  # QA must never kill a render
                log.warning("Cut QA skipped for %s (%s): %s", clip.name, edge, exc)
                continue
            issue = compare_edge(expected, heard, edge)  # type: ignore[arg-type]
            if issue:
                issues.append(issue)
    return issues
