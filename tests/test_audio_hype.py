"""Synthetic-only acceptance checks; no viewer timestamps or learned models."""

import subprocess
import wave
from dataclasses import fields, replace

import numpy as np
import pytest
from autoclip.pipeline.audio_hype import (
    AudioFeatures,
    AudioHypeConfig,
    audio_features,
    compute_audio_hype,
    peaks_from_features,
)
from autoclip.pipeline.ffmpeg import FFmpegError, ffmpeg_path

RATE = 16000


def _noise(seconds, low, high, seed):
    rng = np.random.default_rng(seed)
    n = round(seconds * RATE)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freq = np.fft.rfftfreq(n, 1 / RATE)
    spectrum[(freq < low) | (freq > high)] = 0
    signal = np.fft.irfft(spectrum, n=n)
    return (signal / np.std(signal)).astype(np.float32)


def _wav(path, signal):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes((np.clip(signal, -1, 1) * 32767).astype("<i2").tobytes())
    return path


@pytest.fixture
def reactions(tmp_path):
    # Eight minutes of quiet speech-like noise; independent, isolated events.
    signal = np.tile(_noise(1, 400, 1800, 10), 480) * 0.008
    signal[90 * RATE : 94 * RATE] = _noise(4, 400, 3000, 11) * 0.12
    t = np.arange(3 * RATE) / RATE
    explosion = 0.35 * np.sin(2 * np.pi * 60 * t) + _noise(3, 0, 8000, 12) * 0.12
    signal[220 * RATE : 223 * RATE] = explosion
    t = np.arange(4 * RATE) / RATE
    laugh = _noise(4, 800, 3200, 13) * (0.6 + 0.4 * np.sin(2 * np.pi * 5 * t)) * 0.17
    signal[350 * RATE : 354 * RATE] = laugh
    signal[420 * RATE : 440 * RATE] = _noise(20, 0, 8000, 14) * 0.18
    return _wav(tmp_path / "reactions.wav", signal)


def test_speech_explosion_laughter_music(reactions):
    features = audio_features(reactions)
    peaks = peaks_from_features(features)
    assert peaks
    assert abs(peaks[0].t - 92) <= 10 or abs(peaks[0].t - 352) <= 10
    speech = next(p for p in peaks if abs(p.t - 92) <= 10)
    laugh = next(p for p in peaks if abs(p.t - 352) <= 10)
    assert "laughter-like modulation" in laugh.reasons
    assert "bright shout" in laugh.reasons
    assert all(p.score < speech.score for p in peaks if abs(p.t - 221) < 10)
    assert not any(415 < p.t < 445 for p in peaks)
    assert all(p.sample_messages == [] for p in peaks)
    assert len(features.t) == 480
    assert features.voice_ratio[221] < 0.55
    assert features.modulation[351] > 0.20
    assert features.speech_db[91] > features.speech_db[50] + 10
    # Extraction is independent of chunk boundaries, including fractional hops.
    other = audio_features(reactions, config=AudioHypeConfig(chunk_s=7.3))
    for item in fields(features):
        np.testing.assert_allclose(getattr(features, item.name), getattr(other, item.name))


def test_isolated_speech_peak(tmp_path):
    signal = np.tile(_noise(1, 400, 1800, 20), 300) * 0.008
    signal[150 * RATE : 153 * RATE] *= 15
    peaks = compute_audio_hype(_wav(tmp_path / "speech.wav", signal), top_n=1)
    assert len(peaks) == 1
    assert abs(peaks[0].t - 151) <= 10


def test_long_voiced_loudness_and_impulse_are_suppressed(tmp_path):
    signal = np.tile(_noise(1, 400, 1800, 21), 300) * 0.008
    signal[50 * RATE : 53 * RATE] *= 15
    signal[170 * RATE : 190 * RATE] *= 15
    signal[250 * RATE : 250 * RATE + 320] *= 50
    peaks = compute_audio_hype(_wav(tmp_path / "durations.wav", signal))
    assert abs(peaks[0].t - 51) <= 10
    assert not any(160 < p.t < 200 or 240 < p.t < 260 for p in peaks)


@pytest.mark.parametrize("seconds", [0, 0.2, 2, 5])
def test_silence_and_short(tmp_path, seconds):
    assert compute_audio_hype(_wav(tmp_path / "silence.wav", np.zeros(round(seconds * RATE)))) == []


def test_short_loud_audio(tmp_path):
    assert compute_audio_hype(_wav(tmp_path / "short.wav", _noise(1, 400, 1800, 22) * 0.1)) == []


def test_missing_audio_and_decode_error(tmp_path):
    video = tmp_path / "silent.mkv"
    subprocess.run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=16x16:rate=1:duration=1",
            "-an",
            "-c:v",
            "ffv1",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    assert compute_audio_hype(video) == []
    with pytest.raises(FFmpegError):
        compute_audio_hype(tmp_path / "missing.wav")


def _features(events=(60, 200, 340, 480), size=600):
    t = np.arange(size, dtype=float) + 0.5
    level = np.full(size, -45.0)
    for event in events:
        level[event : event + 3] = -27
    return AudioFeatures(
        t,
        level,
        level + 1,
        np.full(size, 0.8),
        np.full(size, 1500.0),
        np.full(size, 0.2),
        np.full(size, 0.2),
        np.full(size, 0.05),
        np.zeros(size),
        np.full(size, 0.9),
        float(size),
    )


def test_pure_deterministic_ranking_windows_and_override():
    features = _features()
    before = features.speech_db.copy()
    peaks = peaks_from_features(features)
    assert peaks == peaks_from_features(features)
    assert len(peaks) == 4
    assert [p.t for p in peaks] == [60.5, 200.5, 340.5, 480.5]
    assert peaks_from_features(features, top_n=2) == peaks[:2]
    assert peaks_from_features(features, top_n=0) == []
    assert peaks_from_features(features, config=AudioHypeConfig(top_n=1), top_n=2) == peaks[:2]
    for peak in peaks:
        assert peak.window_start == peak.t - 30
        assert peak.window_end == peak.t + 10
    np.testing.assert_array_equal(features.speech_db, before)
    clamped = peaks_from_features(features, duration_s=62)
    assert len(clamped) == 1
    assert clamped[0].window_end == 62


def test_merge_limit_and_clamping():
    peaks = peaks_from_features(_features((5, 50, 100, 150, 200, 250)))
    assert len(peaks) > 1
    assert all(p.window_end - p.window_start <= 150 for p in peaks)
    assert peaks[0].window_start == 0
    assert peaks[0].window_end > peaks[0].t + 10
    separated = peaks_from_features(_features((60, 100)), config=AudioHypeConfig(max_window_s=40))
    assert len(separated) == 2


def test_nan_safe_and_invalid_arguments():
    features = _features()
    features.speech_db[20] = np.nan
    features.centroid[21] = np.inf
    peaks = peaks_from_features(features)
    assert peaks and all(np.isfinite(p.score) for p in peaks)
    for value in (-1, np.nan, np.inf):
        with pytest.raises(ValueError):
            peaks_from_features(features, duration_s=value)
    for value in (-1, 1.5, True):
        with pytest.raises(ValueError):
            peaks_from_features(features, top_n=value)
    with pytest.raises(ValueError):
        peaks_from_features(replace(features, flux=np.zeros(2)))


@pytest.mark.parametrize("name", [f.name for f in fields(AudioHypeConfig)])
def test_config_nonfinite(name):
    for value in (np.nan, np.inf, -np.inf):
        with pytest.raises(ValueError):
            AudioHypeConfig(**{name: value})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hop_s": -1},
        {"hop_s": 0.1},
        {"hop_s": 0.51},
        {"chunk_s": 0},
        {"rolling_window_s": -1},
        {"pre_s": -1},
        {"post_s": -1},
        {"min_z": -1},
        {"top_n": -1},
        {"top_n": 1.5},
        {"top_n": True},
        {"voice_ratio_floor": 1.1},
        {"max_window_s": 39},
        {"burst_max_s": 0.5},
        {"long_loud_s": 5},
        {"chunk_s": 0.5},
        {"burst_weight": -1},
        {"impulse_penalty": 1.1},
    ],
)
def test_config_invalid(kwargs):
    with pytest.raises(ValueError):
        AudioHypeConfig(**kwargs)


def test_default_top_fifteen():
    features = _features(tuple(range(60, 2500, 120)), size=2600)
    assert len(peaks_from_features(features)) == 15
    assert len(peaks_from_features(features, top_n=30)) == 21


def test_half_second_hops_and_partial_tail(tmp_path):
    signal = np.tile(_noise(1, 400, 1800, 23), 20) * 0.008
    signal[10 * RATE : 12 * RATE] *= 15
    path = _wav(tmp_path / "half.wav", np.r_[signal, np.zeros(1234)])
    cfg = AudioHypeConfig(hop_s=0.5, chunk_s=3.1)
    features = audio_features(path, config=cfg)
    assert len(features.t) == 40
    assert features.duration_s == pytest.approx(20 + 1234 / RATE)
    peaks = peaks_from_features(features, config=cfg)
    assert peaks and abs(peaks[0].t - 11) < 2


@pytest.mark.parametrize(
    "name", [f.name for f in fields(AudioHypeConfig) if f.name != "silence_db"]
)
def test_config_negative(name):
    with pytest.raises(ValueError):
        AudioHypeConfig(**{name: -1})
