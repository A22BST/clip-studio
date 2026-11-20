"""Exercise optional overlay behavior without changing existing caption contracts."""

from __future__ import annotations

from pathlib import Path

import pysubs2
import pytest
from autoclip.pipeline import captions
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
    assert max(map(len, lines)) * style.fontsize * 1.2 <= 1080 * 0.8 + 0.01
    assert style.marginv >= 1920 * 0.07
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
