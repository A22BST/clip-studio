"""Exercise optional overlay behavior without changing existing caption contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pysubs2
import pytest
from autoclip.pipeline import captions, ffmpeg
from autoclip.pipeline.transcript import Word


def test_hook_round_trip(tmp_path: Path) -> None:
    path = captions.write_ass(
        tmp_path / "hook.ass",
        [Word("hello", 100, 101)],
        captions.get_style("bold_pop"),
        width=1080,
        height=1920,
        time_offset_s=100,
        hook_text="Watch this",
        hook_duration_s=3,
    )
    subs = pysubs2.load(str(path))
    hook = next(e for e in subs.events if e.style == captions.HOOK_STYLE_NAME)
    assert (hook.start, hook.end) == (0, 3000)
    assert "Watch this" in hook.text and r"\fad(" in hook.text
    assert subs.styles[captions.HOOK_STYLE_NAME].bold
    assert subs.styles[captions.HOOK_STYLE_NAME].alignment == pysubs2.Alignment.TOP_CENTER


def test_no_hook_by_default() -> None:
    subs = captions.build_ass([], captions.get_style("bold_pop"), width=1080, height=1920)
    assert not subs.events
    assert captions.HOOK_STYLE_NAME not in subs.styles


def test_hook_wrap_safe_area() -> None:
    event, style = captions.build_hook_event("WIDE WORDS " * 30, 1080, 1920)
    lines = event.text.split("}", 1)[1].split(r"\N")
    assert len(lines) <= 2
    assert all(captions._overlay_text_width(line, style.fontsize) <= 1080 * 0.9 for line in lines)
    assert style.marginv == round(1920 * 0.02)
    assert event.end == 2000
    event, _ = captions.build_hook_event(r"{\pos(0,0)}hello", 1080, 1920)
    assert r"\pos" not in event.text


@pytest.mark.parametrize("key", list(captions.PRESETS))
def test_center_position(key: str) -> None:
    subs = captions.build_ass(
        [Word("hello", 0, 1), Word("world", 1, 2)],
        captions.get_style(key),
        width=1080,
        height=1920,
        center_y_frac=0.38,
        hook_text="Hook",
    )
    caption_events = [e for e in subs.events if e.style == captions.STYLE_NAME]
    assert all(r"\an5\pos(540,729.6)" in e.text for e in caption_events)
    assert subs.styles[captions.STYLE_NAME].alignment == pysubs2.Alignment.MIDDLE_CENTER
    assert all(r"\pos" not in e.text for e in subs.events if e.style == captions.HOOK_STYLE_NAME)


def test_invalid_center() -> None:
    with pytest.raises(ValueError, match="center_y_frac"):
        captions.build_ass(
            [], captions.get_style("bold_pop"), width=1080, height=1920, center_y_frac=1.1
        )


@pytest.mark.parametrize("width,height", [(1080, 1920), (1080, 1080), (1920, 1080)])
def test_overlay_sizes_and_output_canvas(tmp_path, width, height):
    path = captions.write_ass(
        tmp_path / "overlays.ass",
        [],
        captions.get_style("bold_pop"),
        width=width,
        height=height,
        hook_text="CHAT SAID TYPE 1 AND WE ROBBED THE STORE",
        disclosure_text="#ad Paid partnership",
    )
    subs = pysubs2.load(str(path))
    assert (int(subs.info["PlayResX"]), int(subs.info["PlayResY"])) == (width, height)
    hook = subs.styles[captions.HOOK_STYLE_NAME]
    disclosure = subs.styles[captions.DISCLOSURE_STYLE_NAME]
    assert hook.fontsize == pytest.approx(height * 0.045 / captions._ANTON_CAP_RATIO)
    assert disclosure.fontsize == pytest.approx(height * 0.027 / captions._ANTON_CAP_RATIO)
    assert hook.bold and disclosure.bold
    assert hook.outline >= height / 1920 * 6
    assert disclosure.marginv + disclosure.fontsize <= height * 0.25


def test_libass_visible_overlay_sizes(tmp_path):
    """Catch font fallback, line-height/cap-height confusion and width shrinkage."""
    path = captions.write_ass(
        tmp_path / "captions.ass",
        [],
        captions.get_style("bold_pop"),
        width=1080,
        height=1920,
        hook_text="CHAT SAID TYPE 1 AND WE ROBBED THE STORE",
        disclosure_text="#ad Paid partnership",
    )
    cwd, subtitle, fonts = ffmpeg.relative_filter_workspace(path, captions.FONT_DIR)
    result = subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:d=3",
            "-vf",
            f"ass={subtitle}:fontsdir={fonts}",
            "-ss",
            "1",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        cwd=cwd,
        capture_output=True,
        check=True,
    )
    assert "Anton-Regular" in result.stderr.decode(errors="replace")
    pixels = np.frombuffer(result.stdout, dtype=np.uint8).reshape(1920, 1080, 3)
    rows = np.flatnonzero((pixels.max(axis=2) > 150).any(axis=1))
    runs = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    assert len(runs) == 3  # two hook lines, then the disclosure
    assert all(0.04 * 1920 <= len(run) <= 0.05 * 1920 for run in runs[:2])
    assert len(runs[2]) >= 0.025 * 1920
    columns = np.flatnonzero((pixels.max(axis=2) > 150).any(axis=0))
    assert columns[0] >= 1080 * 0.05
    assert columns[-1] <= 1080 * 0.95
    assert rows[-1] < 0.25 * 1920
    assert runs[1][-1] < runs[2][0]
