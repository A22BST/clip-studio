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


def test_ceiling_filters_duration_and_handles_offset():
    clips = [ViewerClip(100, 900, "outside before", 10),
             ViewerClip(1100, 800, "covered", 30),
             ViewerClip(1400, 700, "uncovered", 30),
             ViewerClip(3000, 1000, "outside after", 30)]
    data = {"candidates": [{"window_start_s": 120, "window_end_s": 150},
                           {"window_start_s": 125, "window_end_s": 155}]}
    assert sc.candidate_ceiling(data, clips, offset_s=1000, top=2, tol=0, max_s=500) == 0.5
    assert sc.candidate_ceiling({"candidates": []}, clips, offset_s=1000,
                                top=2, tol=0, max_s=500) == 0


def test_picked_ranks_uses_explicit_pool_ranks(tmp_path, monkeypatch):
    (tmp_path / "candidates.json").write_text(json.dumps({"candidates": [
        {"rank": 7, "first_word": 0, "last_word": 100},
        {"rank": 3, "first_word": 200, "last_word": 300}]}), encoding="utf-8")
    clips = [type("C", (), {"start_word_index": a, "end_word_index": b})()
             for a, b in [(220, 250), (10, 50)]]
    monkeypatch.setattr(sc, "load_highlights", lambda _p: [(c, None) for c in clips])
    assert sc.picked_ranks(tmp_path) == [3, 7]


def test_multi_job_and_legacy_parsing():
    args = sc.argument_parser().parse_args(["--jobs", "a:v1:10", "b:v2:20:C:/cache/clips.json"])
    assert args.jobs == [("a", "v1", 10.0, None), ("b", "v2", 20.0, Path("C:/cache/clips.json"))]
    args = sc.argument_parser().parse_args(["old", "vod", "--offset-s", "12"])
    assert (args.job, args.vod, args.offset_s) == ("old", "vod", 12)


def test_bad_job_spec():
    import argparse

    import pytest

    for spec in ["a:v", "a:v:bad", ":v:10"]:
        with pytest.raises(argparse.ArgumentTypeError):
            sc.parse_job_spec(spec)


def test_multi_job_tables_means_and_failure_details(tmp_path, monkeypatch, capsys):
    from autoclip.auto.config import AutoConfig
    from autoclip.config import Settings

    for job in ("a", "b"):
        work = tmp_path / job
        work.mkdir()
        (work / "candidates.json").write_text(json.dumps({"stream": {"duration_s": 200},
            "candidates": [{"window_start_s": 90, "window_end_s": 130}]}), encoding="utf-8")
    monkeypatch.setattr(sc.paths, "job_work_dir", lambda job: tmp_path / job)
    monkeypatch.setattr(sc.app_config, "load", Settings)
    monkeypatch.setattr(sc, "targets", lambda *a: (None, [("claude-cli", "test", None, True)]))
    monkeypatch.setattr(sc, "load_config", AutoConfig)
    monkeypatch.setattr(sc, "load_viewer_clips", lambda *a: [ViewerClip(100, 500, "hit", 10)])
    monkeypatch.setattr(sc, "run_target", lambda job, *a: (tmp_path / job, 1, ""))
    monkeypatch.setattr(sc, "pick_spans", lambda work: [(95, 125)] if work.name == "a" else [])
    monkeypatch.setattr(sc, "picked_ranks", lambda work: [4] if work.name == "a" else [])
    monkeypatch.setattr(sys, "argv", ["compare", "--jobs", "a:v:0", "b:v:0"])
    sc.main()
    out = capsys.readouterr().out
    assert "job a" in out and "job b" in out and "[4]  ok" in out
    assert "n=2/2 recall 50% precision 50% CEILING 100%" in out
    monkeypatch.setattr(sc, "run_target", lambda *a: (tmp_path, 1,
        "SelectionError: Attempts: bucket/model=timeout; bucket/other=empty"))
    sc.main()
    out = capsys.readouterr().out
    assert "ERROR claude-cli test:" in out and "bucket/model=timeout; bucket/other=empty" in out
    assert "n=0/2 unavailable" in out


def test_run_target_keeps_complete_attempt_diagnostics(tmp_path, monkeypatch):
    from autoclip.providers.base import ProviderError

    original = tmp_path / "original"
    original.mkdir()
    (original / "candidates.json").write_text('{"candidates": []}', encoding="utf-8")
    monkeypatch.setattr(sc.paths, "job_work_dir",
                        lambda job: original if job == "job" else tmp_path / job)
    attempts = [{"bucket": "bucket", "model": f"model-{i}", "kind": "timeout"}
                for i in range(25)]

    def fail(*args):
        raise sc.select.SelectionError(str(ProviderError("No usable chain entries remain.",
                                                         attempts=attempts)))

    monkeypatch.setattr(sc.select, "run_selection", fail)
    builder = sc.select.build_chain
    _work, _secs, error = sc.run_target("job", "bucket", None, object(), 1, retries=1)
    assert "bucket/model-0=timeout" in error and "bucket/model-24=timeout" in error
    assert sc.select.build_chain is builder
