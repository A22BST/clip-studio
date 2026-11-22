"""SFX library, timeline, command compatibility, and synthetic render coverage."""

from __future__ import annotations

import math
import os
import re
from types import SimpleNamespace
import shutil
import struct
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from autoclip.config import ExportSettings
from autoclip.pipeline import captions, export, ffmpeg, sfx
from autoclip.pipeline.profanity import bleep_audio_filter
from autoclip.pipeline.reframe.croppath import centre_crop


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path))
    folder = tmp_path / "assets" / "sfx" / "viral-clip-sound-effects"
    folder.mkdir(parents=True)
    for name in ["Boom.mp3", "BONE CRACK.MP3", "Riser 2.mp3"]:
        (folder / name).touch()
    return folder


@pytest.mark.parametrize("name", ["boom", "BOOM.MP3", "Boom.mp3"])
def test_resolve(library, name):
    assert sfx.resolve_name(name) == library / "Boom.mp3"
    assert sfx.available_names() == ["BONE CRACK", "Boom", "Riser 2"]
    assert sfx.resolve_name("bone crack") == library / "BONE CRACK.MP3"


def test_unknown_and_ambiguous(library):
    for name in ["missing", "../Boom.mp3", str(library / "Boom.mp3")]:
        with pytest.raises(ValueError, match="Unknown SFX.*Available names:.*Boom"):
            sfx.resolve_name(name)
    (library.parent / "Boom.wav").touch()
    with pytest.raises(ValueError, match="Ambiguous SFX"):
        sfx.resolve_name("Boom")
    assert sfx.resolve_name("Boom.mp3") == library / "Boom.mp3"


@pytest.mark.parametrize(
    "kind,at,duration,expected",
    [
        ("impact", 1.25, 2, (0, 1.25)),
        ("riser", 8.5, 2, (0, 6.5)),
        ("riser", 1, 2.5, (1.5, 0)),
        ("riser", 0, 2, (2, 0)),
    ],
)
def test_alignment(kind, at, duration, expected):
    assert sfx.placement(sfx.SFXEvent(name="test", at_s=at, kind=kind), duration) == expected


@pytest.mark.parametrize(
    "event",
    [
        {"name": "Boom", "at_s": -0.1},
        {"name": "Boom", "at_s": 3.1},
        {"name": "Boom", "at_s": float("nan")},
        {"name": "Boom", "at_s": float("inf")},
        {"name": "Boom", "at_s": 1, "gain_db": float("nan")},
        {"name": "Boom", "at_s": 1, "kind": "music"},
    ],
)
def test_reject_invalid_before_asset_lookup(event):
    with pytest.raises(ValueError):
        sfx.prepare_events([event], 3)


def test_max_events():
    with pytest.raises(ValueError, match="At most 1"):
        sfx.prepare_events([{"name": "Boom", "at_s": 1}] * 2, 3)


def test_probe_and_endpoints(library, monkeypatch):
    monkeypatch.setattr(ffmpeg, "probe", lambda p: ffmpeg.MediaInfo(p, 2, False, True))
    prepared = sfx.prepare_events([{"name": "Boom", "at_s": 0}], 3)
    prepared += sfx.prepare_events([{"name": "Riser 2", "at_s": 3, "kind": "riser"}], 3)
    assert [(e.trim_s, e.delay_s) for e in prepared] == [(0, 0), (0, 1)]
    monkeypatch.setattr(ffmpeg, "probe", lambda p: ffmpeg.MediaInfo(p, 0, False, True))
    with pytest.raises(ValueError, match="duration"):
        sfx.prepare_events([{"name": "Boom", "at_s": 0}], 3)
    monkeypatch.setattr(ffmpeg, "probe", lambda p: ffmpeg.MediaInfo(p, 2, False, False))
    with pytest.raises(ValueError, match="no audio stream"):
        sfx.prepare_events([{"name": "Boom", "at_s": 0}], 3)


def example(kind="impact", at=8.5, duration=2):
    event = sfx.SFXEvent(name="example", at_s=at, kind=kind)
    trim, delay = sfx.placement(event, duration)
    return sfx.PreparedSFX(Path("example.wav"), event, trim, delay, duration, -12.0)


@pytest.mark.parametrize("kind,delay", [("impact", "8500.0000"), ("riser", "6500.0000")])
def test_exact_filtergraph(kind, delay, monkeypatch):
    monkeypatch.setattr(sfx, "measure_rms", lambda path: -12.0)
    graph = sfx.build_filtergraph(
        [example(kind)],
        first_input=1,
        clip_duration_s=20,
        final_filter=export.build_audio_filtergraph(ExportSettings()),
    )
    start = 8.5 if kind == "impact" else 6.5
    end = start + 2
    assert graph == (
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
        f"volume='1-(1-0.354813)*max(0,min(1,min((t-{start:.4f})/0.08,"
        f"({end:.4f}-t)/0.08)))':eval=frame:"
        f"enable='between(t,{start:.4f},{end:.4f})'[main];"
        "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,"
        "atrim=start=0.0000,asetpts=PTS-STARTPTS,volume=4.0000dB,"
        "alimiter=limit=0.9:attack=1:release=30:level=0,"
        f"adelay={delay}:all=1,apad,atrim=duration=20.0000[sfx0];"
        "[main][sfx0]amix=inputs=2:duration=first:normalize=0,"
        "alimiter=limit=0.95:level=0:latency=1,loudnorm=I=-14.0:TP=-1.5:LRA=11.0[aout]"
    )


def request(tmp_path):
    return export.ExportRequest(
        source=tmp_path / "source.mp4",
        destination=tmp_path / "out.mp4",
        start_s=0,
        end_s=3,
        crop_path=centre_crop(160, 90, 3),
        words=[],
        style=captions.get_style("bold_pop"),
        burn_captions=False,
    )


def test_invalid_event_is_export_error(tmp_path):
    req = request(tmp_path)
    req.sfx = [{"name": "Boom", "at_s": 4}]
    with pytest.raises(export.ExportError, match="Invalid SFX:.*within"):
        export.export_clip(req, work_dir=tmp_path)


@pytest.mark.parametrize("overlay", [False, True])
def test_empty_preserves_legacy_command(tmp_path, monkeypatch, overlay):
    req = request(tmp_path)
    req.extra_audio_filter = bleep_audio_filter([(1, 1.2)])
    if overlay:
        req.overlay_path = tmp_path / "logo.png"
    settings = ExportSettings(prefer_hardware_encoder=False)
    captured = []

    def run(args, **kwargs):
        captured.append(args)
        req.destination.write_bytes(b"mock render")

    monkeypatch.setattr(ffmpeg, "run", run)
    monkeypatch.setattr(sfx, "prepare_events", lambda *a: pytest.fail("empty SFX looked up assets"))
    graph = export.build_video_filtergraph(req, subtitle_name=None)
    inputs = ["-i", str(req.source)]
    if overlay:
        graph = export._add_overlay(graph, 1080, 1920)
        inputs += ["-loop", "1", "-framerate", "30", "-i", str(req.overlay_path)]
    # Frozen legacy argv layout: this includes the original map/-af ordering.
    legacy = [
        "-ss",
        "0.0000",
        "-t",
        "3.0000",
        *inputs,
        "-filter_complex",
        graph,
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        "-af",
        req.extra_audio_filter + ",loudnorm=I=-14.0:TP=-1.5:LRA=11.0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(req.destination),
    ]
    export.export_clip(req, work_dir=tmp_path, settings=settings)
    export.export_clip(replace(req, sfx=[]), work_dir=tmp_path, settings=settings)
    assert captured == [legacy, legacy]
    assert ["\0".join(a).encode() for a in captured] == ["\0".join(legacy).encode()] * 2


def test_overlay_input_indices_and_bleep_order(tmp_path, monkeypatch):
    monkeypatch.setattr(sfx, "measure_rms", lambda path: -12.0)
    req = request(tmp_path)
    req.overlay_path = tmp_path / "logo.png"
    req.sfx = [{"name": "Boom", "at_s": 1}]
    req.extra_audio_filter = bleep_audio_filter([(1, 1.2)])
    monkeypatch.setattr(sfx, "prepare_events", lambda *a: [example(at=1), example("riser", 1)])
    captured = []

    def run(args, **kwargs):
        captured.extend(args)
        req.destination.write_bytes(b"mock")

    monkeypatch.setattr(ffmpeg, "run", run)
    export.export_clip(
        req, work_dir=tmp_path, settings=ExportSettings(prefer_hardware_encoder=False)
    )
    graph = captured[captured.index("-filter_complex") + 1]
    assert "[2:a]" in graph and "[3:a]" in graph and "[1:v]" in graph
    assert "[0:a]" + req.extra_audio_filter + ",aformat=" in graph
    assert graph.index(req.extra_audio_filter) < graph.index("amix=") < graph.index("loudnorm=")
    assert "-af" not in captured
    assert captured[captured.index("[vout]") + 2] == "[aout]"


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe unavailable"
)
@pytest.mark.parametrize(
    "kind,payoff,inside",
    [
        ("impact", 1.5, 1.6),
        ("riser", 1.5, 1.1),
        ("riser", 0.3, 0.05),
    ],
)
def test_synthetic_mix(tmp_path, monkeypatch, kind, payoff, inside):
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path))
    monkeypatch.setitem(export.RATIOS, "9:16", (90, 160))
    req = request(tmp_path)
    folder = sfx.library_dir()
    folder.mkdir(parents=True)
    asset = folder / "test.wav"

    def run(*args):
        return subprocess.run(
            [ffmpeg.ffmpeg_path(), "-v", "error", "-y", *args], check=True, capture_output=True
        )

    run(
        "-f",
        "lavfi",
        "-i",
        "color=size=160x90:rate=10:duration=3",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=3",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        str(req.source),
    )
    run("-f", "lavfi", "-i", "sine=frequency=1200:duration=0.5", str(asset))
    req.sfx = [{"name": "TEST", "at_s": payoff, "kind": kind}]
    export.export_clip(
        req, work_dir=tmp_path / "work", settings=ExportSettings(prefer_hardware_encoder=False)
    )
    info = ffmpeg.probe(req.destination)
    assert info.has_audio and info.has_video
    assert info.duration_s == pytest.approx(3, abs=0.1)
    raw = run(
        "-i", str(req.destination), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"
    ).stdout
    samples = struct.unpack(f"<{len(raw) // 4}f", raw)

    def amplitude(start):
        window = samples[int(start * 48000) : int((start + 0.2) * 48000)]
        return abs(
            sum(
                x
                * complex(
                    math.cos(i * 2 * math.pi * 1200 / 48000),
                    math.sin(i * 2 * math.pi * 1200 / 48000),
                )
                for i, x in enumerate(window)
            )
        ) / len(window)

    assert amplitude(inside) > 10 * max(amplitude(0.7), amplitude(2.3), 1e-6)


def test_peak_cache_tracks_mtime(tmp_path, monkeypatch):
    asset = tmp_path / "effect.wav"
    asset.touch()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stderr="Peak level dB: -18.0\nPeak level dB: -12.0\n")

    monkeypatch.setattr(subprocess, "run", run)
    assert sfx.measure_peak(asset) == -12.0
    assert sfx.measure_peak(asset) == -12.0
    assert len(calls) == 1
    stat = asset.stat()
    os.utime(asset, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
    assert sfx.measure_peak(asset) == -12.0
    assert len(calls) == 2
    assert "astats=reset=0" in calls[0][calls[0].index("-af") + 1]


@pytest.mark.parametrize("stderr", ["Peak level dB: -inf", "no measurements"])
def test_reject_unmeasurable_peak(tmp_path, monkeypatch, stderr):
    asset = tmp_path / "silent.wav"
    asset.touch()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stderr=stderr))
    with pytest.raises(ValueError, match="no finite audio peak"):
        sfx.measure_peak(asset)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="ffmpeg required")
def test_effect_loudness_and_unchanged_surroundings(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path))
    sfx.library_dir().mkdir(parents=True)
    asset = sfx.library_dir() / "quiet.wav"
    source = tmp_path / "noise.wav"
    baseline = tmp_path / "baseline.wav"
    ducked_stream = tmp_path / "ducked_stream.wav"
    effect_only = tmp_path / "effect_only.wav"
    mixed = tmp_path / "mixed.wav"

    def run(*args):
        return subprocess.run([ffmpeg.ffmpeg_path(), "-hide_banner", "-nostats", "-y", *args],
                              capture_output=True, text=True, check=True)

    run("-f", "lavfi", "-i", "anoisesrc=amplitude=0.25:duration=6:sample_rate=48000:seed=42",
        str(source))
    run("-f", "lavfi", "-i", "sine=frequency=1200:duration=0.2:sample_rate=48000",
        "-af", "volume=-20dB", str(asset))
    effects = sfx.prepare_events([{"name": "quiet", "at_s": 3}], 6)
    assert sfx.measure_peak(asset) < -35
    # Finished clips keep their existing loudness; only limit peaks after mixing.
    final = "alimiter=limit=0.95:level=0"
    run("-i", str(source), "-af", "aformat=sample_rates=48000:channel_layouts=stereo," + final,
        "-ar", "48000", str(baseline))
    run("-i", str(baseline), "-af", "volume=0.354813:enable='between(t,3,3.2)'",
        str(ducked_stream))
    graph = sfx.build_filtergraph(effects, first_input=1, clip_duration_s=6, final_filter=final)
    run("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=6", "-i", str(asset),
        "-filter_complex", graph, "-map", "[aout]", "-ar", "48000", str(effect_only))
    run("-i", str(source), "-i", str(asset), "-filter_complex", graph,
        "-map", "[aout]", "-ar", "48000", str(mixed))

    def rms(path, start, duration):
        result = run("-ss", str(start), "-i", str(path), "-t", str(duration),
                     "-af", "astats=reset=0", "-f", "null", "-")
        return float(re.findall(r"RMS level dB: ([^\s]+)", result.stderr)[-1])

    assert rms(effect_only, 3.02, .16) >= rms(ducked_stream, 3.02, .16) + 6
    for start in (.5, 4.5):
        assert abs(rms(mixed, start, 1) - rms(baseline, start, 1)) < 1.5
