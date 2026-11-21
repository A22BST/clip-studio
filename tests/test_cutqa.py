from pathlib import Path
from types import SimpleNamespace

import pytest
from autoclip.pipeline import cutqa
from autoclip.pipeline.cutqa import compare_edge
from autoclip.pipeline.layouts import Layout, Rect, default_plan


def test_clean_start_and_end():
    assert compare_edge(["no", "way", "that", "happened"], ["No", "way", "that"], "start") is None
    assert compare_edge(["so", "that", "happened"], ["so", "that", "happened."], "end") is None


def test_start_swallowed_first_word_is_error():
    issue = compare_edge(["no", "way", "that", "happened"], ["way", "that", "happened"], "start")
    assert issue and issue.severity == "error" and "cut off" in issue.message


def test_end_swallowed_last_word_is_error():
    issue = compare_edge(["and", "then", "he", "died"], ["and", "then", "he"], "end")
    assert issue and issue.severity == "error"


def test_unrelated_words_only_warn():
    issue = compare_edge(["hello", "there", "chat"], ["xylophone", "music"], "start")
    assert issue and issue.severity == "warning"


def test_silence_or_nothing_expected_is_fine():
    assert compare_edge(["hello", "chat"], [], "start") is None
    assert compare_edge([], ["hello"], "end") is None


def test_fuzzy_match_tolerates_whisper_spelling():
    assert compare_edge(["gonna", "win"], ["gunna", "win"], "start") is None


@pytest.mark.parametrize(
    "pixels, warns",
    [
        (bytes([0] * 61 + [255] * 39), True),
        (bytes([31] * 60 + [32] * 40), False),
        (bytes([32] * 100), False),
        # Aggregate all sampled frames, not just the first dark frame.
        (bytes([0] * 100 + [255] * 200), False),
        (b"", False),
    ],
)
def test_dark_opening_thresholds(monkeypatch, pixels, warns):
    monkeypatch.setattr(cutqa.ffmpeg, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(
        cutqa.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=pixels)
    )
    issue = cutqa.check_dark_opening(Path("clip.mp4"))
    assert bool(issue) == warns
    if issue:
        assert issue.code == "dark_opening" and issue.severity == "warning"
        assert "0.610" in issue.message


@pytest.mark.parametrize("layout", [None, Layout.FACECAM, Layout.REACTION])
def test_dark_opening_samples_rendered_gameplay(monkeypatch, layout):
    calls = []
    monkeypatch.setattr(cutqa.ffmpeg, "ffmpeg_path", lambda: "ffmpeg")

    def run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs == {"check": True, "capture_output": True, "timeout": 30}
        return SimpleNamespace(stdout=bytes([255]))

    monkeypatch.setattr(cutqa.subprocess, "run", run)
    plan = default_plan(layout, Rect(0, 0, 100, 100)) if layout else None
    assert cutqa.check_dark_opening(Path("clip.mp4"), plan) is None
    cmd = calls[0]
    assert cmd[cmd.index("-t") + 1] == "0.5"
    assert cmd[cmd.index("-frames:v") + 1] == "3"
    filters = cmd[cmd.index("-vf") + 1]
    assert "format=gray" in filters
    assert ("crop=" in filters) == (layout is not None)
    if plan:
        assert str(plan.cam_fraction) in filters


def test_dark_opening_decode_failure_is_nonfatal(monkeypatch):
    monkeypatch.setattr(cutqa.ffmpeg, "ffmpeg_path", lambda: "ffmpeg")

    def fail(*args, **kwargs):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(cutqa.subprocess, "run", fail)
    assert cutqa.check_dark_opening(Path("clip.mp4")) is None
