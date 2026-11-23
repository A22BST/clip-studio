"""Exploratory CPU reaction candidates, independent of chat.

This does not alter the frozen hype-fusion experiment. Mixed VOD audio cannot
prove speaker identity: nearby transcript words suppress speech-free cutscenes,
but game dialogue/music can still pass. Optional autocorrelation F0 estimates
add pitch-jump evidence. All times are local to the supplied audio/transcript.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio_hype import AudioFeatures, AudioHypeConfig, _robust_baseline, audio_features
from .transcript import Transcript
from .transcript_hype import _LAUGH, _token


@dataclass(frozen=True)
class CrashoutConfig:
    baseline_s: float = 120.0
    min_z: float = 1.5
    min_score: float = 2.0
    pitch_ratio: float = 1.2
    pitch_min_s: float = 0.5
    speech_radius_s: float = 12.0
    pre_s: float = 12.0
    post_s: float = 10.0
    context_s: float = 20.0
    merge_gap_s: float = 4.0
    max_window_s: float = 60.0
    per_hour: int = 15

    def __post_init__(self):
        for name, value in vars(self).items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {name}")
        if type(self.per_hour) is not int or self.baseline_s <= 0:
            raise ValueError("per_hour must be an integer and baseline_s positive")
        if self.min_z <= 0:
            raise ValueError("min_z must be positive")
        if self.pitch_ratio <= 1 or self.pitch_min_s <= 0:
            raise ValueError("pitch ratio must exceed one and duration must be positive")
        if self.pre_s + self.post_s < 20 or not 20 <= self.max_window_s <= 60:
            raise ValueError("windows must be 20-60 seconds")
        if self.pre_s + self.post_s > self.max_window_s:
            raise ValueError("max_window_s must cover pre/post roll")


def crashout_from_features(
    features: AudioFeatures,
    transcript: Transcript | None = None,
    *,
    config: CrashoutConfig | None = None,
    diagnostics: dict | None = None,
) -> list[dict]:
    """Return candidates.json-shaped dictionaries, ranked within an hourly budget.

    None transcript permits audio-only detection (reason marks weaker evidence).
    An explicitly empty transcript suppresses every event. Nonverbal reactions
    can bridge up to speech_radius_s to surrounding recognized words.
    """
    cfg = config or CrashoutConfig()
    t = np.asarray(features.t, dtype=float)
    arrays = [
        np.asarray(getattr(features, name), dtype=float)
        for name in (
            "speech_db",
            "full_db",
            "voice_ratio",
            "centroid",
            "flux",
            "zcr",
            "high_share",
            "modulation",
            "occupancy",
        )
    ]
    duration = features.duration_s
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("invalid audio duration")
    if t.ndim != 1 or any(a.shape != t.shape for a in arrays):
        raise ValueError("unaligned feature arrays")
    if not len(t) or duration < 20 or cfg.per_hour == 0:
        return []
    if not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        raise ValueError("feature times must be finite and increasing")
    hop = float(np.median(np.diff(t))) if len(t) > 1 else 1.0
    speech, full, ratio, bright, flux, zcr, high, mod, occupancy = arrays
    valid = np.logical_and.reduce([np.isfinite(a) for a in arrays])
    valid &= (t >= 0) & (t < duration)
    speech = np.where(valid, speech, -120)
    window = max(1, math.ceil(cfg.baseline_s / hop))
    # Condition the rolling reference on speech-like audio: alternating silence
    # and voice otherwise makes MAD measure duty cycle instead of vocal dynamics.
    voiced = valid & (t >= 2) & (speech > -55) & (ratio >= 0.45) & (occupancy >= 0.25)
    baseline, scale = _robust_baseline(speech, window)
    for i in range(1, len(t)):
        lo = max(0, i - window)
        history = speech[lo:i][voiced[lo:i]]
        if len(history) >= min(10, max(2, int(5 / hop))):
            baseline[i] = np.median(history)
            scale[i] = 1.4826 * np.median(np.abs(history - baseline[i]))
    brightness, _ = _robust_baseline(np.where(valid, bright, 0), window)
    rise = speech - baseline
    z = np.maximum(0, rise / np.maximum(scale, 3.0))
    jump = np.r_[0, np.diff(speech)]
    voiced = valid & (t >= 2) & (speech > -55) & (ratio >= 0.45) & (occupancy >= 0.25)
    loud = voiced & (z >= cfg.min_z)
    # Reject sustained soundtrack/engine changes, including their onset.
    lengths = np.zeros(len(t))
    edges = np.flatnonzero(np.diff(np.r_[False, loud, False]))
    for lo, hi in edges.reshape(-1, 2):
        lengths[lo:hi] = (hi - lo) * hop
    pitch = bright > np.maximum(brightness, 300) * 1.30
    f0_jump = np.zeros(len(t), dtype=bool)
    f0_ratio = np.zeros(len(t))
    f0 = getattr(features, "pitch_hz", None)
    if f0 is not None:
        f0 = np.asarray(f0, dtype=float)
        if f0.shape != t.shape:
            raise ValueError("unaligned pitch features")
        # Track preceding voiced pitch only, avoiding a silence-to-voice jump.
        last = 0.0
        history = []
        for i, value in enumerate(f0):
            history = [(time, pitch) for time, pitch in history if time >= t[i] - cfg.baseline_s]
            if math.isfinite(value) and value > 0:
                if history:
                    last = float(np.median([p for _, p in history]))
                    f0_ratio[i] = value / last
                    f0_jump[i] = f0_ratio[i] >= cfg.pitch_ratio
                history.append((t[i], value))
    # Half-second pitch bursts count; sustained changes still get suppressed.
    # Periodicity is already gated in the optional F0 extractor. Reject prolonged
    # pitch changes (music/new game speaker) rather than treating their onset as
    # a reaction; transcript proximity is shared with loudness events below.
    pitch_event = voiced & f0_jump
    pitch_lengths = np.zeros(len(t))
    edges = np.flatnonzero(np.diff(np.r_[False, pitch_event, False]))
    for lo, hi in edges.reshape(-1, 2):
        pitch_lengths[lo:hi] = (hi - lo) * hop
    pitch_event &= (pitch_lengths >= cfg.pitch_min_s) & (pitch_lengths <= 10)
    laugh = (mod >= 0.20) & (flux > 0)
    rate = np.zeros(len(t))
    swears = np.zeros(len(t))
    laughs = np.zeros(len(t))
    nearby = np.ones(len(t), dtype=bool)
    rate_baseline = np.zeros(len(t))
    if transcript is not None:
        # Histograms avoid an O(hops * transcript_words) scan.
        size = max(1, math.ceil(duration))
        word_bins = np.zeros(size)
        swear_bins = np.zeros(size)
        laugh_bins = np.zeros(size)
        for word in transcript.words:
            if not math.isfinite(word.start) or not 0 <= word.start < duration:
                continue
            i = int(word.start)
            word_bins[i] += 1
            tok = _token(word.text)
            swear_bins[i] += tok in {
                "fuck",
                "fucking",
                "shit",
                "bullshit",
                "damn",
                "bitch",
                "wtf",
                "oh",
                "wow",
                "whoa",
                "ah",
                "no",
                "what",
                "hey",
            }
            laugh_bins[i] += bool(_LAUGH.match(tok))

        def counts(values, radius):
            prefix = np.r_[0, np.cumsum(values)]
            lo = np.clip(np.floor(t - radius).astype(int), 0, size)
            hi = np.clip(np.ceil(t + radius).astype(int), 0, size)
            return prefix[hi] - prefix[lo]

        nearby = counts(word_bins, cfg.speech_radius_s) > 0
        rate = counts(word_bins, 2) / 4
        rate_baseline, _ = _robust_baseline(rate, window)
        swears = counts(swear_bins, 2)
        laughs = counts(laugh_bins, 2)
    rate_burst = (rate >= 2) & (rate >= np.maximum(0.5, rate_baseline) * 1.5) & (swears > 0)
    rage = rate_burst
    laugh |= laughs > 0
    # Each independent cue can qualify. Bounded contributions prevent a single
    # badly estimated pitch or a silence-to-speech jump dominating the budget.
    loud_score = np.minimum(z / cfg.min_z, 2)
    pitch_score = np.minimum(np.maximum(f0_ratio - 1, 0) / (cfg.pitch_ratio - 1), 2)
    rate_score = np.minimum(rate / np.maximum(rate_baseline, 0.5) / 1.5, 2)
    score = 2 * np.maximum.reduce(
        [loud_score * loud, pitch_score * pitch_event, rate_score * rate_burst]
    )
    score += 0.5 * np.minimum(loud_score, 1) + 0.5 * pitch_event + 0.5 * rate_burst
    score += 0.25 * laugh
    score += 0.5 * np.minimum(np.maximum(jump, 0) / np.maximum(scale, 3), 1)
    eligible = (
        ((loud & (lengths <= 10)) | pitch_event | (voiced & rate_burst))
        & nearby
        & (score >= cfg.min_score)
    )
    if diagnostics is not None:
        diagnostics.update(
            t=t,
            rise_db=rise,
            z=z,
            f0_ratio=f0_ratio,
            speech_present=voiced,
            nearby=nearby,
            loud=loud,
            pitch=pitch_event,
            rate=rate,
            rate_burst=rate_burst,
            eligible=eligible,
            score=score,
        )
    peaks = []
    for i in np.flatnonzero(eligible):
        if (i and eligible[i - 1] and score[i] <= score[i - 1]) or (
            i + 1 < len(t) and eligible[i + 1] and score[i] < score[i + 1]
        ):
            continue
        signals = ["voice_jump"]
        reasons = [f"speech-band rise {rise[i]:.1f} dB ({z[i]:.1f} robust sd)"]
        if pitch[i]:
            signals.append("bright_shout")
            reasons.append("spectral brightness jump (pitch proxy)")
        if f0_jump[i]:
            signals.append("pitch_jump")
            reasons.append(
                f"voiced autocorrelation pitch rise >= {100 * (cfg.pitch_ratio - 1):.0f}%"
            )
        if pitch[i] and z[i] >= 3:
            signals.append("scream_like")
        if rage[i]:
            signals.append("rage_burst")
            reasons.append(
                f"speech-rate burst {rate[i]:.1f} words/s, "
                f"{int(swears[i])} exclamation/swear tokens/4s"
            )
        if laugh[i]:
            signals.append("laugh_burst")
            reasons.append("laughter token or rhythmic 4-6 Hz envelope")
        reasons.append(
            "nearby transcript speech"
            if transcript is not None
            else "audio only: speaker unverified"
        )
        start = max(0.0, min(float(t[i]) - cfg.pre_s, duration - 20))
        end = min(duration, max(float(t[i]) + cfg.post_s, start + 20))
        peaks.append(
            {
                "peak_t": float(t[i]),
                "hype_score": round(float(score[i]), 2),
                "window_start_s": start,
                "window_end_s": end,
                "hype_reasons": reasons,
                "source": "voice_jump",
                "signals": signals,
                "chat_sample": [],
                "viewer_clips": [],
            }
        )
    # Merge neighboring acoustic events, not merely overlapping context windows.
    # Otherwise ordinary speech chains tile the VOD into arbitrary 60 s blocks.
    merged = []
    for peak in peaks:
        if (
            merged
            and peak["peak_t"] - merged[-1]["event_end_s"] <= cfg.merge_gap_s
            and (peak["window_end_s"] - merged[-1]["window_start_s"] <= cfg.max_window_s)
        ):
            prev = merged[-1]
            best = dict(peak if peak["hype_score"] > prev["hype_score"] else prev)
            best["event_end_s"] = peak["peak_t"]
            best["window_start_s"] = prev["window_start_s"]
            best["window_end_s"] = max(prev["window_end_s"], peak["window_end_s"])
            best["signals"] = sorted(set(prev["signals"] + peak["signals"]))
            best["hype_reasons"] = list(dict.fromkeys(prev["hype_reasons"] + peak["hype_reasons"]))
            merged[-1] = best
        else:
            peak["event_end_s"] = peak["peak_t"]
            merged.append(peak)
    # For recordings >=240 s, partial hours cannot round above the configured cap.
    # Shorter recordings retain one proposal so short-input callers remain useful.
    if diagnostics is not None:
        diagnostics["proposals"] = [dict(p) for p in merged]
    chosen, hours = [], {}
    total_budget = max(1, math.floor(cfg.per_hour * duration / 3600))
    for peak in sorted(merged, key=lambda p: (-p["hype_score"], p["peak_t"])):
        if len(chosen) >= total_budget:
            break
        hour = int(peak["peak_t"] // 3600)
        # Also bound a partial final hour proportionally (at least one).
        budget = min(
            cfg.per_hour,
            max(1, math.floor(cfg.per_hour * min(3600, duration - hour * 3600) / 3600)),
        )
        if hours.get(hour, 0) >= budget:
            continue
        hours[hour] = hours.get(hour, 0) + 1
        peak.pop("event_end_s", None)
        peak["rank"] = len(chosen) + 1
        if transcript is not None:
            first, last = transcript.indices_in_range(
                max(0, peak["window_start_s"] - cfg.context_s), peak["window_end_s"] + cfg.context_s
            )
            peak.update(
                first_word=first,
                last_word=max(first, last - 1),
                transcript=" ".join(w.text for w in transcript.words[first:last]),
            )
        else:
            peak.update(first_word=0, last_word=0, transcript="")
        chosen.append(peak)
    return chosen


def compute_crashout(
    media: Path, transcript: Transcript | None = None, *, config: CrashoutConfig | None = None
) -> list[dict]:
    """Decode in bounded chunks with the existing 16 kHz CPU DSP extractor."""
    return crashout_from_features(
        audio_features(media, config=AudioHypeConfig(hop_s=0.5), include_pitch=True),
        transcript,
        config=config,
    )


def overlap_fraction(a: dict, b: dict) -> float:
    """Intersection / shorter window, used for candidate deduplication."""
    lo, hi = (
        max(a["window_start_s"], b["window_start_s"]),
        min(a["window_end_s"], b["window_end_s"]),
    )
    shorter = min(a["window_end_s"] - a["window_start_s"], b["window_end_s"] - b["window_start_s"])
    return max(0.0, hi - lo) / shorter if shorter > 0 else 0.0


def merge_voice_candidates(chat: list[dict], voice: list[dict]) -> list[dict]:
    """Annotate duplicate chat windows; append independent voice-only windows.

    Preserve chat order/scores and window boundaries (which may exceed 60 s).
    Suppressed voice evidence remains explicit in voice_events, including its
    independent 20-60 s window. Inputs are never mutated.
    """
    result = [dict(c) for c in chat]
    for candidate in voice:
        matches = [c for c in result[: len(chat)] if overlap_fraction(c, candidate) >= 0.5]
        if matches:
            match = max(matches, key=lambda c: overlap_fraction(c, candidate))
            match["signals"] = sorted(set(match.get("signals", []) + candidate["signals"]))
            match["voice_events"] = match.get("voice_events", []) + [dict(candidate)]
        else:
            result.append(dict(candidate))
    for rank, candidate in enumerate(result, 1):
        candidate["rank"] = rank
    return result
