"""YouTube section ingest and camera/no-chat guards, with all media mocked."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from autoclip.pipeline import facecam, hype
from autoclip.pipeline.transcript import Transcript, Word
from autoclip.stream import ingest, pipeline
from autoclip.stream.campaigns import Campaign


def test_youtube_range_command_and_proxy_removal(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path))
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "https_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.setattr(ingest, "disk_free_gb", lambda folder: 100)
    monkeypatch.setattr(ingest.ffmpeg, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ingest.ffmpeg, "probe", lambda path: SimpleNamespace(duration_s=9000))
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        assert not any(
            k.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"} for k in kwargs["env"]
        )
        if "--dump-single-json" in cmd:
            assert "--skip-download" in cmd
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "id": "youtube-id",
                        "duration": 42898,
                        "live_status": "was_live",
                        "title": "GTA VI",
                    }
                ),
            )
        path = ingest.streams_dir() / "youtube-id_9000-18000" / "vod.mp4"
        path.write_bytes(b"mock video")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(ingest.subprocess, "run", run)
    source = ingest.ingest_youtube_vod(
        "https://youtube.com/watch?v=youtube-id", start="2:30:00", end="5:00:00"
    )
    cmd = calls[-1]
    assert cmd[cmd.index("--download-sections") + 1] == "*9000-18000"
    assert cmd[cmd.index("--format") + 1] == "bv*[height<=720]+ba/b[height<=720]"
    assert cmd[cmd.index("--merge-output-format") + 1] == "mp4"
    assert cmd[cmd.index("--output") + 1].endswith("vod.%(ext)s")
    assert "--live-from-start" not in cmd
    assert "--force-keyframes-at-cuts" not in cmd
    assert source.folder.name == "youtube-id_9000-18000"
    assert source.load_chat() is None
    assert source.title == "GTA VI"
    # Reuse does not download the section again.
    ingest.ingest_youtube_vod(source.url, start="2:30:00", end="5:00:00")
    assert sum("--download-sections" in c for c in calls) == 1


@pytest.mark.parametrize("status", ["is_live", "post_live", "is_upcoming"])
def test_live_youtube_never_downloads(tmp_path, monkeypatch, status):
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path))
    monkeypatch.setattr(ingest, "youtube_metadata", lambda url: {"live_status": status})
    monkeypatch.setattr(ingest, "_youtube_run", lambda args: pytest.fail("download attempted"))
    with pytest.raises(ingest.StreamSkipped, match="finished streams only"):
        ingest.ingest_youtube_vod("https://youtube.com/watch?v=id", start=0, end=100)
    assert not ingest.streams_dir().exists()


def test_no_chat_fallback_uses_audio_and_transcript(monkeypatch):
    audio = [hype.HypePeak(20, 4, 10, 30, ["loudness"], [])]
    transcript = Transcript(words=[Word("oh", 95, 96), Word("my", 96, 97), Word("god!", 97, 98)])
    peaks = pipeline.no_chat_peaks(audio, transcript, 120, 15)
    assert any("audio: loudness" in p.reasons for p in peaks)
    assert any(any(r.startswith("transcript:") for r in p.reasons) for p in peaks)
    assert pipeline.no_chat_peaks([], transcript, 120, 15)


@pytest.mark.parametrize("camera", [None, object()])
def test_dylan_slice_camera_guard(tmp_path, monkeypatch, camera):
    detect = Mock(return_value=camera)
    monkeypatch.setattr(facecam, "detect_facecam_geometry", detect)
    source = ingest.StreamSource("id", tmp_path, tmp_path / "vod.mp4", None, duration_s=9000)
    if camera is None:
        with pytest.raises(pipeline.StreamSliceSkipped, match="no webcam/face detected"):
            pipeline.require_campaign_camera(source, "dylan-page-marathon")
    else:
        pipeline.require_campaign_camera(source, "dylan-page-marathon")
    detect.assert_called_once_with(source.video, 0, 9000)
    pipeline.require_campaign_camera(source, "other-campaign")
    assert detect.call_count == 1


@pytest.mark.parametrize("name", ["Dylan Page GTA 6 Marathon", "other-campaign"])
def test_manual_camera_bypasses_slice_guard(tmp_path, monkeypatch, name):
    monkeypatch.setattr(facecam, "detect_facecam_geometry", lambda *a: pytest.fail("detection attempted"))
    source = ingest.StreamSource("id", tmp_path, tmp_path / "vod.mp4", None, duration_s=9000)
    pipeline.require_campaign_camera(
        source, Campaign(name=name, camera_box=[0.684, 0.148, 0.87, 0.459]),
    )


@pytest.mark.parametrize("missing_at", [None, 0, 2])
def test_dylan_render_forces_large_camera_and_never_falls_back(tmp_path, monkeypatch, missing_at):
    from autoclip import paths
    from autoclip.config import Settings
    from autoclip.pipeline import layouts, rules
    from autoclip.pipeline.transcript import Transcript

    monkeypatch.setattr(paths, "exports_dir", lambda: tmp_path / "exports")
    stream = ingest.StreamSource("yt-id", tmp_path, tmp_path / "vod.mp4", None, duration_s=30)
    clip = SimpleNamespace(
        id="clip",
        rank=1,
        title="Reaction",
        hook="Wait",
        start_s=0,
        end_s=15,
        start_word=0,
        end_word=0,
    )
    meta = pipeline.ClipMeta(layout="track")
    prepared = SimpleNamespace(
        job=SimpleNamespace(id="abcdef"),
        source=SimpleNamespace(path=str(stream.video)),
        highlights_path=tmp_path / "highlights.json",
        runner=SimpleNamespace(
            settings=Settings(), workspace=SimpleNamespace(transcript=tmp_path / "t.json")
        ),
    )
    monkeypatch.setattr(pipeline, "load_highlights", lambda path: [])
    monkeypatch.setattr(pipeline, "build_clip_rows", lambda *a: ([(clip, meta)], []))
    monkeypatch.setattr(Transcript, "load", lambda path: Transcript(words=[]))
    monkeypatch.setattr(pipeline.store, "replace_clips", lambda *a: None)
    monkeypatch.setattr(pipeline.store, "update_clip", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.store, "update_job", lambda *a, **k: None)
    camera = SimpleNamespace(webcam=layouts.Rect(0, 0, 200, 200), face_crop=None)
    calls = []

    def detect(*args):
        calls.append(args)
        return None if len(calls) - 1 == missing_at else camera

    monkeypatch.setattr(facecam, "detect_facecam_geometry", detect)
    monkeypatch.setattr(
        rules, "check_clip", lambda *a: SimpleNamespace(passed=False, qa_score=0, violations=[])
    )
    plans = []
    default_plan = layouts.default_plan

    def plan(*a, **k):
        result = default_plan(*a, **k)
        plans.append(result)
        return result

    monkeypatch.setattr(layouts, "default_plan", plan)
    outcomes = pipeline.render(prepared, Campaign(name="Dylan Page GTA 6 Marathon"), stream=stream)
    if missing_at is None:
        assert outcomes[0].layout_used == "facecam"
        assert plans[0].cam_fraction == 0.75
        assert len(calls) == 4
    else:
        assert outcomes[0].status == "rejected"
        assert outcomes[0].layout_used == "-"
        assert not plans
