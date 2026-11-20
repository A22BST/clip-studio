"""Exercise delayed reactions and independent evidence without requiring a real VOD."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import pytest
from autoclip.pipeline.ffmpeg import FFmpegError, ffmpeg_path
from autoclip.pipeline.hype import (
    HypeConfig,
    HypePeak,
    compute_hype,
    evaluate_peaks,
    loudness_series,
)
from autoclip.stream.chat import ChatLog, ChatMessage


def _background(duration: int = 1000, users: int = 2) -> list[ChatMessage]:
    return [
        ChatMessage(float(t), f"regular-{u}", "ordinary conversation")
        for t in range(0, duration, 5)
        for u in range(users)
    ]


def _burst(t: float, *, n: int = 40, text: str = "KEKW") -> list[ChatMessage]:
    return [ChatMessage(t + i / (n + 1), f"fan-{i}", text) for i in range(n)]


def test_delayed_burst_keeps_event_context_and_samples() -> None:
    chat = ChatLog(_background() + _burst(600))
    peaks = compute_hype(chat)
    assert peaks[0].t == 602.5
    assert peaks[0].window_start <= 580
    assert peaks[0].window_end >= 610
    assert "KEKW x40" in peaks[0].reasons
    assert any("baseline" in reason for reason in peaks[0].reasons)
    assert len(peaks[0].sample_messages) == 8
    assert all("KEKW" in line for line in peaks[0].sample_messages)
    assert peaks == compute_hype(chat)


@pytest.mark.parametrize("background_users", [0, 2])
def test_single_spammer_cannot_trigger_peak(background_users: int) -> None:
    messages = _background(users=background_users)
    messages += [ChatMessage(600 + i / 1000, "spammer", "KEKW " * 30) for i in range(500)]
    assert compute_hype(ChatLog(messages)) == []


@pytest.mark.parametrize("users", [1, 3, 20])
def test_constant_quiet_chat_has_no_peaks(users: int) -> None:
    assert compute_hype(ChatLog(_background(users=users))) == []


def test_empty_chat() -> None:
    assert compute_hype(ChatLog()) == []


@pytest.mark.parametrize(
    "text",
    [
        "kekw",
        "LUL",
        "lulw",
        "OMEGALUL",
        "ICANT",
        "????",
        "???",
        "POGGERS",
        "pOg",
        "PogChamp",
        "clip it",
        "CLIP THAT",
        "No WaY",
        "W W W",
        "L L L",
        "lets go",
        "LETSGOOO",
        "OMG",
        "wtf",
        "holy",
        "bro",
    ],
)
def test_phrase_table_is_case_insensitive(text: str) -> None:
    peaks = compute_hype(
        ChatLog(_burst(600, text=text)),
        config=HypeConfig(w_rate=0, w_unique=0),
    )
    assert peaks
    assert any(" x" in reason for reason in peaks[0].reasons)


def test_emote_fragments_count_without_double_counting_body() -> None:
    body = [ChatMessage(600, f"u{i}", "KEKW", ["KEKW"]) for i in range(40)]
    fragments = [ChatMessage(600, f"u{i}", "", ["KEKW"]) for i in range(40)]
    first = compute_hype(ChatLog(body))[0]
    second = compute_hype(ChatLog(fragments))[0]
    assert first.score == second.score
    assert "KEKW x40" in first.reasons
    assert "KEKW x40" in second.reasons


def test_word_boundaries_avoid_accidental_phrase_matches() -> None:
    assert (
        compute_hype(
            ChatLog(_burst(600, text="following broken pogostick")),
            config=HypeConfig(w_rate=0, w_unique=0),
        )
        == []
    )


def test_nearby_windows_merge_and_keep_best_evidence() -> None:
    separate = HypeConfig(merge_gap_s=0)
    messages = _burst(600, n=40) + _burst(670, n=60, text="CLIP IT")
    original = compute_hype(ChatLog(messages), config=separate)
    merged = compute_hype(ChatLog(messages))
    assert len(original) == 2
    assert len(merged) == 1
    assert merged[0].score == original[0].score
    assert merged[0].t == original[0].t
    assert merged[0].reasons == original[0].reasons
    assert merged[0].window_start == min(p.window_start for p in original)
    assert merged[0].window_end == max(p.window_end for p in original)


def test_exact_merge_gap_is_not_merged() -> None:
    peaks = compute_hype(ChatLog(_burst(600) + _burst(700)))
    assert len(peaks) == 2  # 40-second windows leave exactly a 60-second gap.


def test_overlapping_windows_merge_even_with_zero_gap() -> None:
    peaks = compute_hype(ChatLog(_burst(600) + _burst(620)), config=HypeConfig(merge_gap_s=0))
    assert len(peaks) == 1


@pytest.mark.parametrize("explicit", [False, True])
def test_window_clamping_and_partial_last_bin(explicit: bool) -> None:
    chat = ChatLog(_burst(0) + _burst(199), duration_s=201 if not explicit else 0)
    kwargs = {"duration_s": 201} if explicit else {}
    peaks = compute_hype(chat, **kwargs)
    assert len(peaks) == 2
    assert min(p.window_start for p in peaks) == 0
    assert max(p.window_end for p in peaks) == 201
    assert all(0 <= p.window_start <= p.t <= p.window_end <= 201 for p in peaks)
    assert compute_hype(chat, duration_s=0) == []


def test_loudness_and_viewer_clips_change_ranking() -> None:
    chat = ChatLog(_burst(600) + _burst(800))
    config = HypeConfig(w_rate=0, w_unique=0)
    plain = compute_hype(chat, config=config)
    assert plain[0].t == 602.5
    audio = [(float(t), -10.0 if t == 800 else -40.0) for t in range(0, 1000, 5)]
    loud = compute_hype(chat, loudness=audio, config=config)
    clipped = compute_hype(chat, viewer_clips=[802.5], config=config)
    assert loud[0].t == clipped[0].t == 802.5
    assert loud[0].score > plain[0].score
    assert clipped[0].score > plain[0].score
    assert any("loud +" in reason for reason in loud[0].reasons)
    assert any("viewer clips" in reason for reason in clipped[0].reasons)


def test_optional_signals_work_without_chat_and_ignore_invalid_samples() -> None:
    audio = [(float(t), -40.0) for t in range(0, 600, 5)] + [(600, -10)]
    peaks = compute_hype(ChatLog(), loudness=audio)
    assert peaks[0].t == 602.5
    assert compute_hype(ChatLog(), viewer_clips=[600])
    assert (
        compute_hype(
            ChatLog([ChatMessage(float("nan"), "bad", "KEKW")]),
            loudness=[(-1, -20), (0, float("nan")), (5, float("-inf"))],
            viewer_clips=[float("inf"), -5],
        )
        == []
    )


def test_top_n_sorting_and_rolling_baseline_expiry() -> None:
    chat = ChatLog(_background(2000) + _burst(600) + _burst(1000) + _burst(1600))
    peaks = compute_hype(chat, config=HypeConfig(top_n=2))
    assert len(peaks) == 2
    assert peaks[0].score == pytest.approx(peaks[1].score)
    assert peaks[0].t < peaks[1].t
    assert all(math.isfinite(p.score) for p in peaks)
    assert compute_hype(chat, config=HypeConfig(top_n=0)) == []


def test_evaluate_peaks_sorts_and_checks_expanded_windows() -> None:
    peaks = [HypePeak(600, 2, 570, 610, [], []), HypePeak(100, 5, 70, 110, [], [])]
    assert evaluate_peaks(peaks, [130], top_k=1) == 1.0
    assert evaluate_peaks(peaks, [130], top_k=2) == 0.5
    assert evaluate_peaks(peaks, [130], tolerance_s=19) == 0.0
    assert evaluate_peaks(peaks, [570], tolerance_s=0) == 0.5
    assert evaluate_peaks(peaks, [570], top_k=10, tolerance_s=0) == 0.5
    assert evaluate_peaks([], [100]) == 0.0
    assert evaluate_peaks(peaks, []) == 0.0
    assert evaluate_peaks(peaks, [100], top_k=0) == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"bin_s": 0},
        {"rolling_window_s": -1},
        {"pre_s": -1},
        {"w_rate": float("nan")},
        {"top_n": -1},
    ],
)
def test_invalid_config_is_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        HypeConfig(**kwargs)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")
def test_loudness_series_streams_tone_with_burst(tmp_path: Path) -> None:
    media = tmp_path / "tone.wav"
    subprocess.run(
        [
            ffmpeg_path(),
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=4.25",
            "-af",
            "volume=enable='between(t,2,3)':volume=8",
            str(media),
        ],
        check=True,
        capture_output=True,
    )
    series = loudness_series(media, bin_s=1)
    assert [t for t, _ in series] == pytest.approx([0, 1, 2, 3, 4], abs=0.001)
    assert series[2][1] > series[0][1] + 10
    assert all(math.isfinite(db) for _, db in series)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")
def test_loudness_silence_and_missing_audio(tmp_path: Path) -> None:
    silence = tmp_path / "silence.wav"
    video = tmp_path / "silent-video.mp4"
    for source, target in [
        ("anullsrc=r=8000:cl=mono", silence),
        ("color=c=black:s=16x16:r=1", video),
    ]:
        subprocess.run(
            [
                ffmpeg_path(),
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                source,
                "-t",
                "1",
                str(target),
            ],
            check=True,
            capture_output=True,
        )
    assert loudness_series(silence, bin_s=0.5) == [(0, -120), (0.5, -120)]
    assert loudness_series(video) == []
    with pytest.raises(FFmpegError):
        loudness_series(tmp_path / "missing.wav")


def test_loudness_invalid_bin_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        loudness_series(tmp_path / "unused.wav", bin_s=0)


def test_merging_is_capped_by_max_window_s():
    """A long busy stretch must not collapse into one huge window."""
    from autoclip.pipeline.hype import HypeConfig, compute_hype
    from autoclip.stream.chat import ChatLog, ChatMessage

    messages = []
    for base in range(300, 1500, 40):  # a burst every 40 s for 20 minutes
        for k in range(60):
            messages.append(ChatMessage(base + k * 0.1, f"user{k % 12}", "KEKW LUL", ["KEKW"]))
    chat = ChatLog(messages=sorted(messages, key=lambda m: m.t), duration_s=1800)
    peaks = compute_hype(chat, duration_s=1800, config=HypeConfig(top_n=50, max_window_s=120))
    assert peaks and all(p.window_end - p.window_start <= 120 + 1e-6 for p in peaks)
