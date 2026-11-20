"""Audio-only reaction proposals; DSP cues cannot identify the speaker or intent."""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field, fields
from pathlib import Path
from tempfile import TemporaryFile

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .ffmpeg import FFmpegError, ffmpeg_path


@dataclass(frozen=True)
class AudioHypeConfig:
    """Design defaults, independent of chat and viewer clips.

    hop_s is the feature interval (whole 20 ms frames); chunk_s bounds decoded
    waveform memory. rolling_window_s is the preceding median/MAD history.
    pre_s/post_s retain context; merge_gap_s/max_window_s bound merged proposals;
    top_n caps the ranked output. min_z is the candidate threshold and
    db_scale_floor prevents tiny baseline variance amplifying noise. vad_rise_db
    requires speech energy above the local median; voice_ratio_floor rejects
    bass and broadband noise; silence_db is the absolute speech energy floor.
    burst_min_s/burst_max_s define short reactions; long_loud_s marks music-like
    sustained runs. modulation_floor selects rhythmic envelope power at 4-6 Hz;
    bright_ratio selects centroid rises relative to the local baseline.
    impulse_share rejects hops whose energy occupies very few 20 ms frames.
    burst_weight/modulation_weight/bright_weight add evidence; long_penalty and
    impulse_penalty attenuate ambiguous events. min_history_s avoids startup
    guesses. max_z caps extreme rises; centroid_floor_hz stabilizes brightness
    during silence. high_share_floor/zcr_floor identify high-frequency noise.
    The decoder is fixed at 16 kHz mono, with 300-3400 Hz speech energy.
    """

    hop_s: float = 1.0
    chunk_s: float = 60.0
    rolling_window_s: float = 300.0
    pre_s: float = 30.0
    post_s: float = 10.0
    merge_gap_s: float = 60.0
    max_window_s: float = 150.0
    top_n: int = 15
    min_z: float = 2.0
    db_scale_floor: float = 3.0
    vad_rise_db: float = 3.0
    voice_ratio_floor: float = 0.55
    silence_db: float = -70.0
    burst_min_s: float = 1.0
    burst_max_s: float = 6.0
    long_loud_s: float = 10.0
    modulation_floor: float = 0.20
    bright_ratio: float = 1.20
    impulse_share: float = 0.25
    burst_weight: float = 1.0
    modulation_weight: float = 2.0
    bright_weight: float = 1.0
    long_penalty: float = 0.10
    impulse_penalty: float = 0.10
    min_history_s: float = 2.0
    max_z: float = 12.0
    centroid_floor_hz: float = 300.0
    high_share_floor: float = 0.55
    zcr_floor: float = 0.40

    def __post_init__(self) -> None:
        positive = {
            "hop_s",
            "chunk_s",
            "rolling_window_s",
            "db_scale_floor",
            "bright_ratio",
            "burst_min_s",
            "burst_max_s",
            "long_loud_s",
            "min_history_s",
            "max_z",
            "centroid_floor_hz",
        }
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "top_n":
                if type(value) is not int or value < 0:
                    raise ValueError("top_n must be a nonnegative integer")
            elif not math.isfinite(value) or (
                value <= 0 if item.name in positive else value < 0 and item.name != "silence_db"
            ):
                raise ValueError(f"invalid {item.name}")
        if self.hop_s < 0.5 or not math.isclose(self.hop_s / 0.02, round(self.hop_s / 0.02)):
            raise ValueError("hop_s must be >= 0.5 and a multiple of 0.02")
        if self.chunk_s < self.hop_s or self.rolling_window_s < self.hop_s:
            raise ValueError("chunk and baseline must cover at least one hop")
        if self.max_window_s < self.pre_s + self.post_s:
            raise ValueError("max_window_s must cover pre_s + post_s")
        if self.burst_max_s < self.burst_min_s or self.long_loud_s < self.burst_max_s:
            raise ValueError("burst duration bounds must be ordered")
        for name in (
            "voice_ratio_floor",
            "modulation_floor",
            "impulse_share",
            "long_penalty",
            "impulse_penalty",
            "high_share_floor",
            "zcr_floor",
        ):
            if getattr(self, name) > 1:
                raise ValueError(f"{name} must be <= 1")


@dataclass
class AudioPeak:
    """Match HypePeak's editing interface without introducing chat evidence."""

    t: float
    score: float
    window_start: float
    window_end: float
    reasons: list[str]
    sample_messages: list[str] = field(default_factory=list)


@dataclass
class AudioFeatures:
    """Aligned 1-D per-hop arrays; times are hop centers, levels are dBFS.

    flux is positive change in normalized subframe spectra; modulation is the
    fraction of envelope AC power in 4-6 Hz. occupancy is effective occupied
    frame share (mean energy squared / mean squared energy). duration_s retains
    the actual decoded duration, including a discarded partial final hop.
    Only these small arrays grow with duration; decoded PCM is chunk bounded.
    """

    t: np.ndarray
    speech_db: np.ndarray
    full_db: np.ndarray
    voice_ratio: np.ndarray
    centroid: np.ndarray
    flux: np.ndarray
    zcr: np.ndarray
    high_share: np.ndarray
    modulation: np.ndarray
    occupancy: np.ndarray
    duration_s: float


def _chunk_features(pcm: np.ndarray, hop_frames: int) -> np.ndarray:
    frames = pcm.reshape(-1, hop_frames, 320).astype(np.float32) / 32768.0
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(320), axis=-1)) ** 2
    spectrum[..., 1:-1] *= 2
    freq = np.fft.rfftfreq(320, 1 / 16000)
    total = spectrum.sum(axis=-1)
    speech = spectrum[..., (freq >= 300) & (freq <= 3400)].sum(axis=-1)
    # Hann power normalization gives dBFS on the same scale as time-domain RMS.
    norm = 320 * np.square(np.hanning(320)).sum()
    full_energy = total.mean(axis=1)
    speech_energy = speech.mean(axis=1)
    centroid = (spectrum * freq).sum(axis=-1) / np.maximum(total, 1e-20)
    normalized = spectrum / np.maximum(total[..., None], 1e-20)
    flux = np.maximum(np.diff(normalized, axis=1), 0).sum(axis=-1).mean(axis=1)
    envelope = np.sqrt(speech / norm)
    ac = np.abs(np.fft.rfft(envelope - envelope.mean(axis=1, keepdims=True), axis=1)) ** 2
    rates = np.fft.rfftfreq(hop_frames, 0.02)
    modulation = ac[:, (rates >= 4) & (rates <= 6)].sum(axis=1) / np.maximum(
        ac[:, 1:].sum(axis=1), 1e-20
    )
    return np.column_stack(
        [
            10 * np.log10(np.maximum(speech_energy / norm, 1e-12)),
            10 * np.log10(np.maximum(full_energy / norm, 1e-12)),
            speech_energy / np.maximum(full_energy, 1e-20),
            centroid.mean(axis=1),
            flux,
            (np.diff(np.signbit(frames), axis=-1) != 0).mean(axis=(1, 2)),
            spectrum[..., freq > 3400].sum(axis=(1, 2)) / np.maximum(total.sum(axis=1), 1e-20),
            modulation,
            total.mean(axis=1) ** 2 / np.maximum(np.square(total).mean(axis=1), 1e-20),
        ]
    )


def audio_features(media: Path, *, config: AudioHypeConfig | None = None) -> AudioFeatures:
    """Stream ffmpeg PCM; missing audio is empty, other decode errors are explicit.

    Incomplete final hops are discarded, avoiding padding-induced impulses.
    Stderr goes to a temporary file so a full pipe cannot deadlock the decoder.
    """
    cfg = config or AudioHypeConfig()
    hop_frames = round(cfg.hop_s / 0.02)
    hop_samples = hop_frames * 320
    chunk_bytes = max(1, int(cfg.chunk_s / cfg.hop_s)) * hop_samples * 2
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(media),
        "-map",
        "0:a:0?",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "s16le",
        "-",
    ]
    blocks = []
    decoded_bytes = 0
    with (
        TemporaryFile() as errors,
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors) as proc,
    ):
        try:
            assert proc.stdout is not None
            pending = b""
            while data := proc.stdout.read(chunk_bytes):
                decoded_bytes += len(data)
                pending += data
                usable = len(pending) // (hop_samples * 2) * (hop_samples * 2)
                if usable:
                    blocks.append(
                        _chunk_features(np.frombuffer(pending[:usable], "<i2"), hop_frames)
                    )
                    pending = pending[usable:]
            proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        if proc.returncode:
            errors.seek(0, 2)
            errors.seek(max(0, errors.tell() - 8192))
            error = errors.read().decode("utf-8", errors="replace")
            if "does not contain any stream" not in error:
                raise FFmpegError("Audio analysis failed.", command=command, stderr=error)
    values = np.concatenate(blocks) if blocks else np.empty((0, 9))
    return AudioFeatures(
        (np.arange(len(values)) + 0.5) * cfg.hop_s,
        *(values[:, i] for i in range(9)),
        decoded_bytes / 32000,
    )


def _robust_baseline(values: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Exact preceding median/MAD, in bounded batches rather than a VOD-sized matrix."""
    padded = np.pad(values, (window, 0), constant_values=np.nan)
    views = sliding_window_view(padded, window)[: len(values)]
    centers = np.zeros(len(values))
    scales = np.zeros(len(values))
    # Expanding startup avoids all-NaN reduction warnings.
    for i in range(1, min(window, len(values))):
        history = values[:i]
        centers[i] = np.median(history)
        scales[i] = 1.4826 * np.median(np.abs(history - centers[i]))
    for start in range(window, len(values), 256):
        batch = views[start : start + 256]
        median = np.median(batch, axis=1)
        centers[start : start + len(batch)] = median
        scales[start : start + len(batch)] = 1.4826 * np.median(
            np.abs(batch - median[:, None]), axis=1
        )
    return centers, scales


def peaks_from_features(
    features: AudioFeatures,
    *,
    duration_s: float | None = None,
    config: AudioHypeConfig | None = None,
    top_n: int | None = None,
) -> list[AudioPeak]:
    """Rank immutable feature input; stable ties and merging mirror chat hype."""
    cfg = config or AudioHypeConfig()
    limit = cfg.top_n if top_n is None else top_n
    if type(limit) is not int or limit < 0:
        raise ValueError("top_n must be a nonnegative integer")
    duration = features.duration_s if duration_s is None else duration_s
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("duration_s must be finite and nonnegative")
    arrays = [np.asarray(getattr(features, f.name), dtype=float) for f in fields(features)[:-1]]
    if any(a.ndim != 1 or len(a) != len(arrays[0]) for a in arrays):
        raise ValueError("feature arrays must be aligned and one-dimensional")
    if not limit or duration < cfg.min_history_s + cfg.hop_s or not len(arrays[0]):
        return []
    t, speech, full, ratio, centroid, flux, zcr, high, modulation, occupancy = arrays
    valid = np.logical_and.reduce([np.isfinite(a) for a in arrays])
    valid &= (t >= 0) & (t < duration)
    if np.any(np.diff(t[np.isfinite(t)]) <= 0):
        raise ValueError("feature times must be increasing")
    # Invalid hops become finite silence and never become candidates.
    speech = np.where(valid, np.clip(speech, -120, 0), -120)
    centroid = np.where(valid, np.clip(centroid, 0, 8000), 0)
    window = max(1, math.ceil(cfg.rolling_window_s / cfg.hop_s))
    baseline, scale = _robust_baseline(speech, window)
    center, _ = _robust_baseline(centroid, window)
    z = np.clip((speech - baseline) / np.maximum(scale, cfg.db_scale_floor), 0, cfg.max_z)
    gate = valid & (speech > cfg.silence_db) & (speech - baseline >= cfg.vad_rise_db)
    gate &= (ratio >= cfg.voice_ratio_floor) & (t >= cfg.min_history_s)
    loud = gate & (z >= cfg.min_z)
    # Label contiguous runs once; suppress the onset as well as the tail of music.
    boundaries = np.flatnonzero(np.diff(np.r_[False, loud, False]))
    run_length = np.zeros(len(t))
    for start, end in boundaries.reshape(-1, 2):
        run_length[start:end] = (end - start) * cfg.hop_s
    burst = (run_length >= cfg.burst_min_s) & (run_length <= cfg.burst_max_s)
    laugh = (modulation >= cfg.modulation_floor) & (flux > 0)
    bright = centroid > np.maximum(center, cfg.centroid_floor_hz) * cfg.bright_ratio
    score = z + cfg.burst_weight * burst + cfg.modulation_weight * laugh
    score += cfg.bright_weight * bright
    score *= np.where(run_length > cfg.long_loud_s, cfg.long_penalty, 1)
    # High-frequency broadband transients are especially suspect; voice ratio is
    # already a hard gate. Effective frame occupancy catches short impulses.
    impulsive = (occupancy < cfg.impulse_share) | (
        (high > cfg.high_share_floor) & (zcr > cfg.zcr_floor)
    )
    score *= np.where(impulsive, cfg.impulse_penalty, 1)
    score = np.where(gate & np.isfinite(score), score, 0)
    candidates = []
    for i, value in enumerate(score):
        if value < cfg.min_z or value <= 0:
            continue
        if (i and value <= score[i - 1]) or (i + 1 < len(score) and value < score[i + 1]):
            continue
        why = [f"speech-band +{z[i]:.1f} sd", f"voice ratio {ratio[i]:.2f}"]
        if burst[i]:
            why.append("short voiced burst")
        if laugh[i]:
            why.append("laughter-like modulation")
        if bright[i]:
            why.append("bright shout")
        candidates.append(
            AudioPeak(
                float(t[i]),
                float(value),
                max(0.0, float(t[i]) - cfg.pre_s),
                min(float(t[i]) + cfg.post_s, duration),
                why,
            )
        )
    merged: list[AudioPeak] = []
    for peak in candidates:
        if (
            merged
            and (
                peak.window_start <= merged[-1].window_end
                or peak.window_start - merged[-1].window_end < cfg.merge_gap_s
            )
            and max(merged[-1].window_end, peak.window_end) - merged[-1].window_start
            <= cfg.max_window_s
        ):
            previous = merged[-1]
            best = peak if peak.score > previous.score else previous
            merged[-1] = AudioPeak(
                best.t,
                best.score,
                previous.window_start,
                max(previous.window_end, peak.window_end),
                best.reasons,
            )
        else:
            merged.append(peak)
    return sorted(merged, key=lambda p: (-p.score, p.t))[:limit]


def compute_audio_hype(
    media: Path,
    *,
    duration_s: float | None = None,
    config: AudioHypeConfig | None = None,
    top_n: int | None = None,
) -> list[AudioPeak]:
    """Decode once and return audio-only editing proposals in descending score."""
    cfg = config or AudioHypeConfig()
    # Validate overrides before starting an expensive decode.
    if duration_s is not None and (not math.isfinite(duration_s) or duration_s < 0):
        raise ValueError("duration_s must be finite and nonnegative")
    if top_n is not None and (type(top_n) is not int or top_n < 0):
        raise ValueError("top_n must be a nonnegative integer")
    if top_n == 0 or (top_n is None and cfg.top_n == 0):
        return []
    features = audio_features(media, config=cfg)
    duration = features.duration_s if duration_s is None else min(duration_s, features.duration_s)
    return peaks_from_features(features, duration_s=duration, config=cfg, top_n=top_n)
