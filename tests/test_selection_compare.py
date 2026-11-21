"""The comparison script's pure parts (no network, no models)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import selection_compare as sc  # noqa: E402
from autoclip.stream.hype_eval import ViewerClip  # noqa: E402


def test_score_recall_and_precision():
    clips = [ViewerClip(100.0, 500, "a", 30.0), ViewerClip(900.0, 400, "b", 30.0)]
    spans = [(95.0, 125.0), (3000.0, 3030.0)]
    recall, precision = sc.score(spans, clips, offset_s=0.0, top=2, tol=30.0)
    assert recall == 0.5
    assert precision == 0.5


def test_pick_spans_maps_words_to_seconds(tmp_path, monkeypatch):
    (tmp_path / "candidates.json").write_text(
        json.dumps({"candidates": [{"first_word": 0, "last_word": 100,
                                    "window_start_s": 100.0, "window_end_s": 200.0}]}),
        encoding="utf-8")
    clip = type("C", (), {"start_word_index": 10, "end_word_index": 50})()
    monkeypatch.setattr(sc, "load_highlights", lambda _p: [(clip, None)])
    assert sc.pick_spans(tmp_path) == [(110.0, 150.0)]
