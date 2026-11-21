"""Fused hype detection: pool chat, audio and transcript candidates, then rank them.

The pooling step is deterministic code; the ranking step is a Claude judgement made with the
frozen prompt in docs/hype-fusion-protocol.md (the ranker only ever sees transcript text, a chat
sample and signal scores, never viewer-clip data). ``rrf_rank`` is a no-LLM fallback and a
secondary experimental arm. Evaluation helpers (coverage, random baseline) live here too so the
protocol's numbers come from tested code.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..pipeline.transcript import Transcript
from . import hype_eval

#: Window length cap and tolerance fixed by the protocol.
MAX_WINDOW_S = 150.0
TOLERANCE_S = 30.0
#: Reciprocal-rank-fusion constant for the no-LLM arm.
RRF_K = 10


@dataclass
class Candidate:
    id: int
    start: float
    end: float
    t: float  # time of the strongest member peak
    #: source -> (rank within that source starting at 1, score)
    signals: dict[str, tuple[int, float]] = field(default_factory=dict)
    reasons: dict[str, list[str]] = field(default_factory=dict)
    chat_sample: list[str] = field(default_factory=list)

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def rrf(self) -> float:
        return sum(1.0 / (RRF_K + rank) for rank, _ in self.signals.values())


def pool_candidates(
    sources: dict[str, Sequence[Any]],
    *,
    max_window_s: float = MAX_WINDOW_S,
    merge_gap_s: float = 0.0,
) -> list[Candidate]:
    """Union peaks from every source into candidate windows.

    ``sources`` maps a name ("chat", "audio", "transcript") to peaks already sorted best-first
    (anything with ``t``, ``score``, ``window_start``, ``window_end``, ``reasons`` and optional
    ``sample_messages``). Overlapping windows (or windows closer than ``merge_gap_s``) are
    merged while the union stays within ``max_window_s``; otherwise they stay separate
    candidates. Ids are assigned in time order, so they carry no ranking information.
    """
    items: list[tuple[float, float, float, str, int, float, list[str], list[str]]] = []
    for name, peaks in sources.items():
        for rank, p in enumerate(peaks, start=1):
            items.append(
                (
                    p.window_start,
                    p.window_end,
                    p.t,
                    name,
                    rank,
                    p.score,
                    list(p.reasons),
                    list(getattr(p, "sample_messages", []) or []),
                )
            )
    items.sort(key=lambda x: (x[0], x[1], x[3]))
    groups: list[list[tuple]] = []
    for item in items:
        if groups:
            g_start = groups[-1][0][0]
            g_end = max(x[1] for x in groups[-1])
            if item[0] - g_end <= merge_gap_s and max(g_end, item[1]) - g_start <= max_window_s:
                groups[-1].append(item)
                continue
        groups.append([item])
    result: list[Candidate] = []
    for i, group in enumerate(groups):
        cand = Candidate(
            id=i + 1,
            start=min(x[0] for x in group),
            end=max(x[1] for x in group),
            t=max(group, key=lambda x: (x[5], -x[4]))[2],
        )
        for _s, _e, _t, name, rank, score, why, sample in group:
            if name not in cand.signals or rank < cand.signals[name][0]:
                cand.signals[name] = (rank, score)
            cand.reasons.setdefault(name, [])
            cand.reasons[name].extend(r for r in why if r not in cand.reasons[name])
            if sample and not cand.chat_sample:
                cand.chat_sample = sample
        result.append(cand)
    return result


def rrf_rank(candidates: Sequence[Candidate], top_n: int = 15) -> list[Candidate]:
    """Reciprocal-rank fusion of the per-source ranks (no LLM). Ties break by time."""
    return sorted(candidates, key=lambda c: (-c.rrf, c.t))[:top_n]


def window_text(transcript: Transcript, start: float, end: float, *, max_chars: int = 2500) -> str:
    """Transcript words inside a window, as the ranker sees them."""
    first, last = transcript.indices_in_range(start, end)
    text = " ".join(w.text for w in transcript.words[first:last])
    return text if len(text) <= max_chars else text[:max_chars] + " ..."


# --------------------------------------------------------------------------
# Evaluation helpers
# --------------------------------------------------------------------------


def coverage(windows: Sequence[tuple[float, float]], duration_s: float) -> float:
    """Fraction of the slice covered by the union of the windows."""
    if duration_s <= 0:
        return 0.0
    covered, edge = 0.0, 0.0
    for a, b in sorted(windows):
        a, b = max(0.0, a), min(duration_s, b)
        if b <= max(a, edge):
            continue
        covered += b - max(a, edge)
        edge = b
    return covered / duration_s


def select_truth(
    clips: Sequence[hype_eval.ViewerClip],
    *,
    offset_s: float,
    duration_s: float,
    top_clips: int = 10,
    min_views: int = 0,
) -> list[hype_eval.ViewerClip]:
    """The slice's ground-truth clips, re-timed to slice time (most viewed first)."""
    pool = [c for c in clips if c.views >= min_views]
    _rate, details = hype_eval.hit_rate(
        pool, [], top_clips=top_clips, offset_s=offset_s, max_s=duration_s
    )
    return [c for c, _ in details]


def hits(
    truth: Sequence[hype_eval.ViewerClip],
    windows: Sequence[tuple[float, float]],
    *,
    overlap: bool,
    tolerance_s: float = TOLERANCE_S,
) -> int:
    """Number of truth clips (already in slice time) touching a window +/- tolerance."""
    rate, details = hype_eval.hit_rate(
        list(truth), list(windows), top_clips=len(truth), tolerance_s=tolerance_s, overlap=overlap
    )
    return sum(hit for _, hit in details)


def random_hit_counts(
    truth: Sequence[hype_eval.ViewerClip],
    lengths: Sequence[float],
    duration_s: float,
    *,
    overlap: bool,
    sets: int = 1000,
    seed: int = 20261120,
) -> list[int]:
    """Hit counts of ``sets`` random window sets with the given lengths (deterministic)."""
    if not truth or not lengths:
        return [0] * sets
    rng = random.Random(seed)
    counts: list[int] = []
    for _ in range(sets):
        windows = []
        for length in lengths:
            length = min(length, duration_s)
            a = rng.uniform(0.0, max(0.0, duration_s - length))
            windows.append((a, a + length))
        counts.append(hits(truth, windows, overlap=overlap))
    return counts


def percentile95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)] if ordered else 0.0


def random_baseline(
    truth: Sequence[hype_eval.ViewerClip],
    lengths: Sequence[float],
    duration_s: float,
    *,
    overlap: bool,
    sets: int = 1000,
    seed: int = 20261120,
) -> tuple[float, float]:
    """Mean and 95th-percentile hit rate of random window sets with the given lengths."""
    if not truth or not lengths:
        return 0.0, 0.0
    counts = random_hit_counts(truth, lengths, duration_s, overlap=overlap, sets=sets, seed=seed)
    rates = [c / len(truth) for c in counts]
    return sum(rates) / len(rates), percentile95(rates)


def wilson(hits_: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = hits_ / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
