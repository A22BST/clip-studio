import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from autoclip.pipeline import highlights
from autoclip.pipeline.rules import ClipFacts, check_clip
from autoclip.pipeline.transcript import Transcript, Word
from autoclip.stream import pipeline
from autoclip.stream.campaigns import Campaign
from autoclip.stream.chat import parse_twitchdownloader_json
from autoclip.stream import hype_eval
from autoclip.stream.ingest import StreamSource


@pytest.fixture
def viewer_clip_prepare(monkeypatch, tmp_path):
    from autoclip.config import Settings
    from autoclip.pipeline import hype

    stream = StreamSource(
        vod_id="123456789", folder=tmp_path, video=tmp_path / "v.mp4",
        chat_path=None, trim_start_s=100,
    )
    job = SimpleNamespace(id="job")
    source = SimpleNamespace(duration_s=120)
    transcript = Transcript(words=[Word(f"w{i}", i, i + 0.9) for i in range(120)])
    runner = SimpleNamespace(
        workspace=SimpleNamespace(root=tmp_path),
        _stage_prepare=lambda: tmp_path / "a.wav",
        _stage_transcribe=lambda _audio: transcript,
        _load_or_detect_silences=lambda _audio: [],
    )
    monkeypatch.setattr(pipeline, "job_for_stream", lambda *a: (job, source))
    monkeypatch.setattr(pipeline, "PipelineRunner", lambda *a, **kw: runner)
    monkeypatch.setattr(pipeline.store, "update_job", lambda *a, **kw: None)
    monkeypatch.setattr(hype, "loudness_series", lambda _audio: [])
    compute = Mock(return_value=[hype.HypePeak(45, 3, 30, 60, [], [])])
    monkeypatch.setattr(hype, "compute_hype", compute)
    monkeypatch.setattr(hype_eval, "user_env", lambda _name: "test-credential")
    fetch = Mock(return_value=[])
    monkeypatch.setattr(hype_eval, "fetch_viewer_clips", fetch)
    notes = []

    def run():
        prepared = pipeline.prepare(
            stream, Campaign(name="c"), settings=Settings(), on_status=notes.append,
        )
        return json.loads(prepared.candidates_path.read_text(encoding="utf-8"))

    return SimpleNamespace(stream=stream, compute=compute, fetch=fetch, notes=notes, run=run)


@pytest.mark.parametrize("missing", ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"])
def test_prepare_skips_viewer_clips_without_credentials(viewer_clip_prepare, monkeypatch, missing):
    case = viewer_clip_prepare
    monkeypatch.setattr(hype_eval, "user_env", lambda name: None if name == missing else "set")
    result = case.run()
    case.fetch.assert_not_called()
    assert case.compute.call_args.kwargs["viewer_clips"] == []
    assert result["stream"]["viewer_clips_used"] == 0
    assert result["candidates"][0]["viewer_clips"] == []
    assert "Skipping viewer clips: Twitch credentials missing" in case.notes


def test_prepare_skips_viewer_clips_on_api_error(viewer_clip_prepare):
    case = viewer_clip_prepare
    case.fetch.side_effect = hype_eval.TwitchApiError("private API error details")
    result = case.run()
    case.fetch.assert_called_once_with("123456789")
    assert case.compute.call_args.kwargs["viewer_clips"] == []
    assert result["stream"]["viewer_clips_used"] == 0
    assert "Skipping viewer clips: fetch failed" in case.notes
    assert all("private API error details" not in note for note in case.notes)


def test_prepare_skips_viewer_clips_for_unknown_vod(viewer_clip_prepare):
    case = viewer_clip_prepare
    case.stream.vod_id = "local-video"
    result = case.run()
    case.fetch.assert_not_called()
    assert result["stream"]["viewer_clips_used"] == 0
    assert "Skipping viewer clips: VOD id unknown" in case.notes


@pytest.mark.parametrize("raw_start", [None, 200])
def test_prepare_shifts_and_attaches_top_viewer_clips(viewer_clip_prepare, raw_start):
    case = viewer_clip_prepare
    shift = case.stream.trim_start_s
    if raw_start is not None:
        (case.stream.folder / "chat_raw.json").write_text(
            json.dumps({"video": {"start": raw_start}}), encoding="utf-8",
        )
        shift = raw_start
    case.fetch.return_value = [
        hype_eval.ViewerClip(shift + t, views, f"moment {views}")
        for t, views in [(-1, 999), (120, 999), (40, 10), (45, 100),
                         (50, 50), (55, 20), (90, 200)]
    ]
    result = case.run()
    assert case.compute.call_args.kwargs["viewer_clips"] == [90, 45, 50, 55, 40]
    assert result["stream"]["viewer_clips_used"] == 5
    assert result["candidates"][0]["viewer_clips"] == [
        {"view_count": 100, "title": "moment 100", "offset_s": 45},
        {"view_count": 50, "title": "moment 50", "offset_s": 50},
        {"view_count": 20, "title": "moment 20", "offset_s": 55},
    ]


def test_load_highlights_parses_levels_layouts_and_blur_words(tmp_path):
    path = tmp_path / "h.json"
    path.write_text(
        json.dumps(
            {
                "clips": [
                    {
                        "start_word_index": 5,
                        "end_word_index": 40,
                        "title": "t",
                        "hook": "h",
                        "score": 70,
                        "spoiler_level": "reaction-to-spoiler",
                        "layout": "reaction",
                        "blur_word_ranges": [[10, 14]],
                        "mentions": ["Kreek"],
                    }
                ]
            }
        )
    )
    ((cand, meta),) = pipeline.load_highlights(path)
    assert cand.start_word_index == 5 and meta.blur_word_ranges == [(10, 14)]
    assert meta.spoiler_level == "reaction-to-spoiler" and meta.mentions == ["Kreek"]


@pytest.mark.parametrize("bad", [{"spoiler_level": "spicy"}, {"layout": "wide"}])
def test_load_highlights_rejects_unknown_values(tmp_path, bad):
    item = {"start_word_index": 1, "end_word_index": 9, "title": "t", **bad}
    path = tmp_path / "h.json"
    path.write_text(json.dumps({"clips": [item]}))
    with pytest.raises(pipeline.StreamPipelineError):
        pipeline.load_highlights(path)


def test_blur_windows_follow_refined_start_not_the_picked_word():
    words = [Word(f"w{i}", float(i), i + 0.9) for i in range(100)]
    transcript = Transcript(words=words)
    clip = SimpleNamespace(start_s=20.0, end_s=60.0)  # refinement moved the start to 20 s
    notes: list[str] = []
    (win,) = pipeline._blur_windows([(30, 33)], transcript, clip, notes)
    assert win.start_s == pytest.approx(30 - 20 - 0.15) and win.end_s == pytest.approx(
        33.9 - 20 + 0.15
    )
    assert pipeline._blur_windows([(80, 85)], transcript, clip, notes) == []
    assert any("outside the clip" in n for n in notes)


def test_reaction_clip_without_reaction_layout_is_blocked():
    camp = Campaign(name="c", min_duration_s=10, max_duration_s=90)
    facts = ClipFacts(
        duration_s=30, title="t", hook="h", spoiler_level="reaction-to-spoiler",
        reaction_layout_ok=False,
    )  # fmt: skip
    result = check_clip(camp, facts)
    assert not result.passed and any(v.code == "reaction_needs_layout" for v in result.violations)
    facts.reaction_layout_ok = True
    assert check_clip(camp, facts).passed  # light policy: kept


def test_raw_cinematic_is_always_blocked():
    camp = Campaign(name="c", min_duration_s=10, max_duration_s=90, spoiler_policy="none")
    res = check_clip(
        camp, ClipFacts(duration_s=30, title="t", hook="h", spoiler_level="raw-cinematic")
    )
    assert not res.passed


def test_trimmed_chat_download_is_shifted_by_video_start():
    raw = {
        "video": {"id": "1", "start": 100, "end": 200, "length": 100},
        "comments": [
            {
                "content_offset_seconds": 90,
                "commenter": {"name": "a"},
                "message": {"body": "early"},
            },
            {"content_offset_seconds": 130, "commenter": {"name": "b"}, "message": {"body": "x"}},
        ],
    }
    log = parse_twitchdownloader_json(raw).shifted(-100)
    assert [m.t for m in log.messages] == [30.0]  # the pre-trim message is dropped


def test_stream_date_unknown_is_none_so_today_only_blocks(tmp_path):
    stream = SimpleNamespace(folder=tmp_path, video=tmp_path / "v.mp4")
    assert pipeline._stream_date(stream) is None
    camp = Campaign(name="c", min_duration_s=1, max_duration_s=90, today_only=True)
    res = check_clip(camp, ClipFacts(duration_s=30, title="t", hook="h"))
    assert any(v.code == "missing_stream_date" for v in res.violations)


def test_audible_words_skip_bleeped_and_masked_words():
    words = [
        Word("fuck", 10.0, 10.4),
        Word("it", 10.4, 10.6),
        Word("you", 11.0, 11.3),
        Word("f***", 12, 12.2),
    ]
    assert pipeline._audible_words(words, 10.0, [(0.0, 0.45)]) == ["you"]
    assert pipeline._audible_words(words, 10.0, []) == ["fuck", "it", "you"]


@pytest.mark.parametrize("duration", [20, 35, 45])
def test_highlight_quality_targets_are_not_hard_limits(duration):
    assert highlights.quality_warnings(duration, "one two three four five six") == []


def test_highlight_quality_warnings_keep_valid_campaign_clip():
    hook = "one two three four five six seven"
    notes = highlights.quality_warnings(45.1, hook)
    assert len(notes) == 2
    assert "long_clip warning" in notes[0] and "45.1s" in notes[0]
    assert "hook_too_long warning" in notes[1] and "7 words" in notes[1]
    result = check_clip(Campaign(name="c", min_duration_s=10, max_duration_s=90),
                        ClipFacts(duration_s=45.1, title="t", hook=hook))
    assert result.passed


def test_refined_highlight_warnings_reach_both_reports(monkeypatch, tmp_path):
    from autoclip.providers import ClipCandidate

    transcript = Transcript(words=[Word("word", 0, 50)])
    monkeypatch.setattr(Transcript, "load", lambda _path: transcript)
    monkeypatch.setattr(pipeline, "refine", lambda *a, **kw: SimpleNamespace(
        start_s=10, end_s=60, start_word=0, end_word=0
    ))
    prepared = SimpleNamespace(
        job=SimpleNamespace(id="job"),
        runner=SimpleNamespace(
            workspace=SimpleNamespace(transcript=tmp_path / "t.json", audio=tmp_path / "a.wav"),
            _load_or_detect_silences=lambda _path: [],
        ),
    )
    candidate = ClipCandidate(start_word_index=0, end_word_index=0, title="t",
                              hook="one two three four five six seven", score=70)
    rows, rejected = pipeline.build_clip_rows(
        prepared, [(candidate, pipeline.ClipMeta())],
        Campaign(name="c", min_duration_s=10, max_duration_s=90),
    )
    assert len(rows) == 1 and rejected == []
    clip, meta = rows[0]
    assert len(meta.warnings) == 2
    outcome = pipeline.ClipOutcome(
        rank=1, title=clip.title, hook=clip.hook, start_s=clip.start_s, end_s=clip.end_s,
        layout_requested="track", layout_used="track", spoiler_level="none",
        status="exported", notes=[*meta.warnings, "dark_opening warning (start): fraction 0.890"],
    )
    pipeline.write_report([outcome], tmp_path, campaign="c")
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))[0]
    assert report["status"] == "exported" and report["violations"] == []
    for code in ("long_clip", "hook_too_long", "dark_opening"):
        assert any(code in note for note in report["notes"])
        assert code in (tmp_path / "report.md").read_text(encoding="utf-8")
