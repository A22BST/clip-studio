import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from autoclip.config import Settings
from autoclip.pipeline import reframe, sfx
from autoclip.pipeline.transcript import Transcript, Word
from autoclip.stream import pipeline
from autoclip.stream.campaigns import Campaign


@pytest.fixture
def wiring(monkeypatch, tmp_path):
    transcript = Transcript(words=[Word(f"word{i}.", i, i + 0.9) for i in range(30)])
    monkeypatch.setattr(Transcript, "load", lambda _path: transcript)
    workspace = SimpleNamespace(
        transcript=tmp_path / "transcript.json", audio=tmp_path / "audio.wav",
        captions_dir=tmp_path / "captions",
    )
    prepared = SimpleNamespace(
        job=SimpleNamespace(id="job"),
        source=SimpleNamespace(path=str(tmp_path / "source.mp4")),
        highlights_path=tmp_path / "highlights.json",
        runner=SimpleNamespace(
            workspace=workspace, settings=Settings(), _load_or_detect_silences=lambda _path: [],
        ),
    )
    monkeypatch.setattr(pipeline.paths, "exports_dir", lambda: tmp_path / "exports")
    for name in ("replace_clips", "update_clip", "create_export", "update_job"):
        monkeypatch.setattr(pipeline.store, name, Mock())
    monkeypatch.setattr(reframe, "build_crop_path", lambda *a, **kw: None)
    monkeypatch.setattr(pipeline.cutqa, "check_clip_edges", lambda *a: [])
    monkeypatch.setattr(pipeline.cutqa, "check_dark_opening", lambda *a: None)
    monkeypatch.setattr(sfx, "library_dir", lambda: tmp_path / "sfx")
    (tmp_path / "sfx").mkdir()
    (tmp_path / "sfx" / "impact.wav").write_bytes(b"mock audio")
    monkeypatch.setattr(sfx.ffmpeg, "probe", lambda _path: SimpleNamespace(
        has_audio=True, duration_s=0.5,
    ))
    requests = []

    def export(request, **_kwargs):
        requests.append(request)
        request.destination.write_bytes(b"mock video")

    monkeypatch.setattr(pipeline.export, "export_clip", export)
    item = {
        "start_word_index": 0, "end_word_index": 29,
        "title": "A complete story", "hook": "Watch what happens", "score": 80,
        "caption": "A caption", "hashtags": ["GTA6"], "mentions": ["creator"],
        "story": {
            "setup": {"start_s": 0, "end_s": 3, "text": "The plan"},
            "change": {"start_s": 5, "end_s": 8, "text": "The surprise"},
            "payoff": {"start_s": 15, "end_s": 18, "text": "The reaction"},
        },
        "sfx": [{"name": "impact", "at_s": 18}],
    }

    def run():
        prepared.highlights_path.write_text(json.dumps({"clips": [item]}), encoding="utf-8")
        return pipeline.render(
            prepared, Campaign(name="test", min_duration_s=20, max_duration_s=35),
            stream=SimpleNamespace(folder=tmp_path),
        )

    return SimpleNamespace(
        item=item, run=run, prepared=prepared, requests=requests,
        report_dir=tmp_path / "exports" / "job",
    )


def test_story_and_sfx_reach_export_and_reports(wiring):
    case = wiring
    (outcome,) = case.run()
    ((candidate, meta),) = pipeline.load_highlights(case.prepared.highlights_path)
    assert candidate.story.model_dump() == meta.story == case.item["story"] | {
        name: {**beat, "speech_based": False} for name, beat in case.item["story"].items()
    }
    assert meta.caption == "A caption" and meta.mentions == ["creator"]
    assert len(case.requests) == 1
    assert case.requests[0].sfx == meta.sfx == case.item["sfx"]
    assert case.requests[0].start_s == 0
    assert outcome.status == "exported" and outcome.sfx == "impact"
    assert outcome.story == meta.story
    report = json.loads((case.report_dir / "report.json").read_text(encoding="utf-8"))[0]
    markdown = (case.report_dir / "report.md").read_text(encoding="utf-8")
    assert report["sfx"] == "impact" and "sfx: impact" in report["notes"]
    assert "- sfx: impact" in markdown
    for name, beat in case.item["story"].items():
        assert f"- {name}: {beat['start_s']}s-{beat['end_s']}s: {beat['text']}" in markdown


@pytest.mark.parametrize("events", [
    [{"name": "unknown", "at_s": 18}],
    [{"name": "impact", "at_s": 100}],
    [{"name": "impact", "at_s": -1}],
    [{"name": "impact", "at_s": 5}, {"name": "impact", "at_s": 18}],
])
def test_invalid_sfx_renders_without_effect_with_warning(wiring, events):
    wiring.item["sfx"] = events
    (outcome,) = wiring.run()
    assert outcome.status == "exported" and outcome.sfx == ""
    assert wiring.requests[0].sfx == []
    assert any("sfx warning:" in note and "without sfx" in note for note in outcome.notes)
    report = json.loads((wiring.report_dir / "report.json").read_text(encoding="utf-8"))[0]
    assert any("sfx warning:" in note for note in report["notes"])


def test_story_rejection_writes_zero_clip_report(wiring):
    wiring.item["story"]["payoff"]["text"] = ""
    with pytest.raises(pipeline.StreamPipelineError, match="No usable clips"):
        wiring.run()
    assert wiring.requests == []
    report = json.loads((wiring.report_dir / "report.json").read_text(encoding="utf-8"))[0]
    assert report["status"] == "rejected"
    assert report["story"]["payoff"]["text"] == ""
    assert "story reject: payoff_text_empty_speech" in report["notes"]
    assert "story reject: payoff_text_empty_speech" in (
        wiring.report_dir / "report.md"
    ).read_text(encoding="utf-8")


def test_legacy_pick_renders_with_story_warning(wiring):
    del wiring.item["story"]
    del wiring.item["sfx"]
    (outcome,) = wiring.run()
    assert outcome.status == "exported" and outcome.story is None
    assert wiring.requests[0].sfx == []
    assert any("story ok: story_missing warning: legacy pick" == note for note in outcome.notes)


def test_invalid_story_keeps_indexed_validation_error(wiring):
    wiring.item["story"]["payoff"]["end_s"] = 10
    with pytest.raises(pipeline.StreamPipelineError, match=r"clips\[1\] is invalid:"):
        wiring.run()


def test_auto_sfx_reaches_export_and_report(wiring, monkeypatch):
    from autoclip.pipeline import sfx_auto

    wiring.item["sfx"] = []
    event = {"name": "impact", "at_s": 12, "gain_db": sfx.DEFAULT_GAIN_DB, "kind": "impact"}
    suggest = Mock(return_value=[event])
    monkeypatch.setattr(sfx_auto, "suggest_events", suggest)
    outcome, = wiring.run()
    request, = wiring.requests
    assert request.sfx == [event] and outcome.sfx == "impact"
    assert suggest.call_args.args == (
        wiring.prepared.runner.workspace.audio, request.start_s, request.end_s,
    )
    assert suggest.call_args.kwargs["seed"]
    report = json.loads((wiring.report_dir / "report.json").read_text(encoding="utf-8"))[0]
    assert report["sfx"] == "impact"


@pytest.mark.parametrize("manual,enabled", [(True, True), (False, False)])
def test_auto_sfx_respects_manual_and_setting(wiring, monkeypatch, manual, enabled):
    from autoclip.pipeline import sfx_auto

    if not manual:
        wiring.item["sfx"] = []
    wiring.prepared.runner.settings.auto_sfx = enabled
    monkeypatch.setattr(sfx_auto, "suggest_events", lambda *a, **kw: pytest.fail("unexpected auto SFX"))
    outcome, = wiring.run()
    assert outcome.status == "exported"


def test_auto_sfx_failure_is_nonfatal(wiring, monkeypatch):
    from autoclip.pipeline import sfx_auto

    wiring.item["sfx"] = []
    monkeypatch.setattr(sfx_auto, "suggest_events", Mock(side_effect=OSError("decode failed")))
    outcome, = wiring.run()
    assert outcome.status == "exported" and wiring.requests[0].sfx == []
    assert any("auto sfx warning: decode failed" in note for note in outcome.notes)
