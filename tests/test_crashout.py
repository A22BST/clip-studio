"""Synthetic CPU-DSP checks; no trained models or VOD data required."""

import copy
import wave

import numpy as np
import pytest
from autoclip.pipeline.audio_hype import AudioHypeConfig, audio_features
from autoclip.pipeline.crashout import (
    CrashoutConfig,
    crashout_from_features,
    merge_voice_candidates,
    overlap_fraction,
)
from autoclip.pipeline.transcript import Transcript, Word


def tone(tmp_path, bursts=(), duration=100, silence=False, modulation=False, pitch_only=False):
    sr = 16000
    t = np.arange(sr * duration) / sr
    amp = np.full(len(t), 0.0 if silence else 0.015)
    freq = np.full(len(t), 350.0 if pitch_only else 500.0)
    for lo, hi in bursts:
        mask = (t >= lo) & (t < hi)
        amp[mask] = 0.015 if pitch_only else 0.35
        freq[mask] = 550 if pitch_only else 1000
        if modulation:
            amp[mask] *= 0.55 + 0.45 * np.sin(2 * np.pi * 5 * t[mask])
    pcm = (amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    path = tmp_path / "synthetic.wav"
    with wave.open(str(path), "wb") as w:
        w.setparams((1, 2, sr, 0, "NONE", "not compressed"))
        w.writeframes(pcm.tobytes())
    return audio_features(path, config=AudioHypeConfig(hop_s=0.5), include_pitch=pitch_only)


def test_loud_burst_is_independent_and_has_context(tmp_path):
    f = tone(tmp_path, [(40, 43)])
    result = crashout_from_features(f)
    assert len(result) == 1
    c = result[0]
    assert c["source"] == "voice_jump"
    assert "bright_shout" in c["signals"]
    assert c["window_start_s"] <= 40 < c["window_end_s"]
    assert 20 <= c["window_end_s"] - c["window_start_s"] <= 60
    assert c["chat_sample"] == []


@pytest.mark.parametrize("silence", [True, False])
def test_silence_and_steady_tone_are_not_reactions(tmp_path, silence):
    assert crashout_from_features(tone(tmp_path, silence=silence)) == []


def test_transcript_gap_suppression_and_nonverbal_bridge(tmp_path):
    f = tone(tmp_path, [(40, 43)])
    assert crashout_from_features(f, Transcript()) == []
    assert crashout_from_features(f, Transcript(words=[Word("talk", 10, 11)])) == []
    result = crashout_from_features(f, Transcript(words=[Word("wow", 49, 50)]))
    assert result
    assert "wow" in result[0]["transcript"]


def test_long_loud_cutscene_and_impulse_suppressed(tmp_path):
    f = tone(tmp_path, [(40, 65)])
    assert crashout_from_features(f) == []
    f = tone(tmp_path, [(40, 40.02)])
    assert crashout_from_features(f) == []


def test_rage_and_laugh_cues(tmp_path):
    f = tone(tmp_path, [(40, 43)], modulation=True)
    words = [Word("fuck" if i % 2 else "laughing", 39 + i * 0.2, 39.1 + i * 0.2) for i in range(18)]
    result = crashout_from_features(f, Transcript(words=words))
    assert {"rage_burst", "laugh_burst"} <= set(result[0]["signals"])


def test_close_bursts_merge_and_budget(tmp_path):
    f = tone(tmp_path, [(30, 32), (34, 36), (80, 82)])
    result = crashout_from_features(f, config=CrashoutConfig(per_hour=100))
    assert len(result) == 2
    assert any(c["window_start_s"] < 30 and c["window_end_s"] > 36 for c in result)
    assert len(crashout_from_features(f, config=CrashoutConfig(per_hour=1))) == 1


def test_dedupe_preserves_chat_and_evidence_and_inputs():
    chat = [{"rank": 1, "window_start_s": 10.0, "window_end_s": 50.0, "hype_score": 2}]
    voice = [
        {
            "rank": 1,
            "window_start_s": 20.0,
            "window_end_s": 42.0,
            "source": "voice_jump",
            "signals": ["voice_jump"],
        }
    ]
    original = copy.deepcopy((chat, voice))
    merged = merge_voice_candidates(chat, voice)
    assert len(merged) == 1
    assert merged[0]["window_start_s"] == 10
    assert merged[0]["voice_events"][0]["source"] == "voice_jump"
    assert (chat, voice) == original
    new = dict(voice[0], window_start_s=80.0, window_end_s=102.0)
    assert overlap_fraction(chat[0], new) == 0
    assert len(merge_voice_candidates(chat, [new])) == 2
    assert merge_voice_candidates([], voice)[0]["source"] == "voice_jump"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"per_hour": -1},
        {"per_hour": 1.5},
        {"baseline_s": 0},
        {"min_z": 0},
        {"max_window_s": 80},
        {"pre_s": 1},
    ],
)
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        CrashoutConfig(**kwargs)


def test_invalid_features_rejected(tmp_path):
    f = tone(tmp_path)
    f.t[1] = f.t[0]
    with pytest.raises(ValueError):
        crashout_from_features(f)


def test_short_audio_and_tail_window(tmp_path):
    assert crashout_from_features(tone(tmp_path, duration=10)) == []
    result = crashout_from_features(tone(tmp_path, [(98, 100)]))
    assert result
    assert result[0]["window_end_s"] == 100
    assert result[0]["window_end_s"] - result[0]["window_start_s"] >= 20


def test_dsp_laughter_without_transcript_tokens(tmp_path):
    result = crashout_from_features(tone(tmp_path, [(40, 43)], modulation=True))
    assert "laugh_burst" in result[0]["signals"]


def test_optional_pitch_estimate_and_jump(tmp_path):
    from autoclip.pipeline.audio_hype import VoiceAudioFeatures, _chunk_pitch

    sr = 16000
    t = np.arange(sr * 4) / sr
    pcm = (np.sin(2 * np.pi * 200 * t) * 8000).astype("<i2")
    pitch = _chunk_pitch(pcm, 50)
    assert np.all(np.abs(pitch - 200) < 10)
    f = tone(tmp_path, [(40, 43)])
    f0 = np.full(len(f.t), 200.0)
    f0[(f.t >= 40) & (f.t < 43)] = 400
    voice = VoiceAudioFeatures(**vars(f), pitch_hz=f0)
    assert "pitch_jump" in crashout_from_features(voice)[0]["signals"]


def test_optional_features_remain_compatible_with_frozen_audio_ranker(tmp_path):
    from autoclip.pipeline.audio_hype import VoiceAudioFeatures, peaks_from_features

    f = tone(tmp_path, [(40, 43)])
    voice = VoiceAudioFeatures(**vars(f), pitch_hz=np.full(len(f.t), 200.0))
    assert peaks_from_features(voice) == peaks_from_features(f)


def test_constant_amplitude_pitch_burst_is_an_independent_candidate(tmp_path):
    f = tone(tmp_path, [(40, 43)], pitch_only=True)
    # Both tones are in the speech band with equal amplitude.
    assert abs(f.speech_db[40] - f.speech_db[30]) < 1
    result = crashout_from_features(f, Transcript(words=[Word("wow", 42, 43)]))
    assert result
    assert "pitch_jump" in result[0]["signals"]
    assert result[0]["window_start_s"] < 40 < result[0]["window_end_s"]
    assert crashout_from_features(f, Transcript()) == []


def test_pitch_only_short_burst_counts_but_sustained_change_is_suppressed(tmp_path):
    assert crashout_from_features(tone(tmp_path, [(40, 41)], pitch_only=True))
    assert not crashout_from_features(tone(tmp_path, [(40, 60)], pitch_only=True))


@pytest.mark.parametrize("seconds", [0.5, 1.0, 2.0])
@pytest.mark.parametrize("pitch_only", [False, True])
def test_short_sharp_bursts_count(tmp_path, seconds, pitch_only):
    result = crashout_from_features(tone(tmp_path, [(40, 40 + seconds)], pitch_only=pitch_only))
    assert result
    assert any(c["window_start_s"] <= 40 < c["window_end_s"] for c in result)


def test_loud_but_normal_local_stretch_does_not_fire(tmp_path):
    features = tone(tmp_path, duration=120)
    # The same steady speech at a much higher recording level has zero local z.
    features.speech_db += 20
    features.full_db += 20
    diagnostics = {}
    assert not crashout_from_features(features, diagnostics=diagnostics)
    assert np.max(diagnostics["z"][features.t >= 2]) < 0.01


def test_hourly_cap_selects_highest_scoring_events(tmp_path):
    from autoclip.pipeline.audio_hype import AudioFeatures

    f = tone(tmp_path, duration=100)
    n = 7200
    arrays = {
        name: np.resize(getattr(f, name), n).copy()
        for name in vars(f)
        if name not in {"t", "duration_s"}
    }
    arrays["speech_db"][:] = -35
    arrays["full_db"][:] = -35
    arrays["occupancy"][:] = 1
    arrays["voice_ratio"][:] = 1
    for i in range(120, n - 60, 90):
        arrays["speech_db"][i] += 10 + (i % 7)
    expanded = AudioFeatures(t=np.arange(n) + 0.5, duration_s=n, **arrays)
    result = crashout_from_features(expanded)
    assert len(result) == 30
    assert all(sum(int(c["peak_t"] // 3600) == hour for c in result) == 15 for hour in range(2))


def test_speech_rate_burst_can_qualify_without_pitch_or_loudness(tmp_path):
    f = tone(tmp_path)
    words = [Word("what" if i == 0 else "word", 40 + i * 0.1, 40.05 + i * 0.1) for i in range(20)]
    result = crashout_from_features(f, Transcript(words=words))
    assert result
    assert "rage_burst" in result[0]["signals"]


def test_context_overlap_does_not_chain_separate_events(tmp_path):
    f = tone(tmp_path, [(30, 31), (46, 47)])
    result = crashout_from_features(f, config=CrashoutConfig(per_hour=100))
    assert len(result) == 2
    assert all(c["window_end_s"] - c["window_start_s"] <= 23 for c in result)


def test_partial_hour_budget_never_exceeds_rate(tmp_path):
    from autoclip.pipeline.audio_hype import AudioFeatures

    f = tone(tmp_path, duration=100)
    n = 2120
    arrays = {
        name: np.resize(getattr(f, name), n).copy()
        for name in vars(f)
        if name not in {"t", "duration_s"}
    }
    arrays["speech_db"][:] = -35
    for i in range(120, n - 30, 40):
        arrays["speech_db"][i] += 20
    expanded = AudioFeatures(t=np.arange(n) + 0.5, duration_s=n, **arrays)
    result = crashout_from_features(expanded)
    assert len(result) == 8
    assert len(result) / (n / 3600) <= 15


def test_loud_normal_varying_speech_uses_local_scale(tmp_path):
    f = tone(tmp_path, duration=180)
    f.speech_db[:] = -15 + 2 * np.sin(2 * np.pi * f.t / 5)
    f.full_db[:] = f.speech_db
    diagnostics = {}
    assert not crashout_from_features(f, diagnostics=diagnostics)
    assert np.max(diagnostics["z"][f.t >= 120]) < 1.5
