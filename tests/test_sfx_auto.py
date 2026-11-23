"""DSP peak selection and lossless video passthrough for post-render SFX."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import numpy as np
import pytest

from autoclip.pipeline import ffmpeg, sfx, sfx_auto


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path))
    folder = sfx.library_dir() / "pack"
    folder.mkdir(parents=True)
    for name in ("Boom", "BONE CRACK", "Riser 2", "CLICK", "KEYBOARD TYPING"):
        (folder / f"{name}.wav").touch()
    return folder


def audio(path, *, burst=True, duration=12, onset=6):
    samples = np.random.default_rng(42).normal(0, .005, int(16000 * duration))
    if burst:
        samples[int(onset * 16000):int((onset + .3) * 16000)] *= 30
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def test_story_anchor_and_rotation(library, tmp_path):
    path = audio(tmp_path / "signal.wav")
    story = {"payoff": {"start_s": 6, "text": "mauled by a shark"}}
    first, = sfx_auto.suggest_events(path, 0, 12, "a", story=story, transcript=[])
    second, = sfx_auto.suggest_events(path, 0, 12, "a", story=story, transcript=[])
    assert first["at_s"] == pytest.approx(6, abs=.05)
    assert first["name"] != second["name"]
    assert first["kind"] == "impact" and first["gain_db"] == sfx.DEFAULT_GAIN_DB


def test_no_context_means_no_effect(library, tmp_path):
    assert sfx_auto.suggest_events(audio(tmp_path / "peak.wav"), 0, 12, "a", transcript=[]) == []


@pytest.mark.parametrize("onset", [1, 2.9, 10.6, 11])
def test_excluded_anchors(library, tmp_path, onset):
    story = {"payoff": {"start_s": onset, "text": "crash"}}
    assert sfx_auto.suggest_events(audio(tmp_path / "flat.wav", burst=False), 0, 12, "a",
                                   story=story, transcript=[]) == []


def test_window_offset(library, tmp_path):
    path = audio(tmp_path / "source.wav", duration=20, onset=11)
    story = {"payoff": {"start_s": 11, "text": "crash"}}
    assert sfx_auto.suggest_events(path, 5, 17, "a", story=story,
                                   transcript=[])[0]["at_s"] == pytest.approx(6, abs=.05)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_add_sfx_end_to_end(library, tmp_path):
    def run(*args):
        return subprocess.run([ffmpeg.ffmpeg_path(), "-v", "error", "-y", *args],
                              capture_output=True, check=True)

    source = tmp_path / "clip_9x16.mp4"
    run("-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=6",
        "-f", "lavfi", "-i",
        "sine=frequency=440:duration=6", "-af", "volume=if(between(t\\,3.5\\,3.8)\\,1\\,0.02):eval=frame",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source))
    run("-f", "lavfi", "-i", "sine=frequency=1000:duration=0.3", str(library / "Boom.wav"))
    run("-f", "lavfi", "-i", "sine=frequency=1000:duration=0.3", str(library / "BONE CRACK.wav"))
    original = source.read_bytes()
    stat = source.stat()
    script = Path(__file__).resolve().parents[1] / "scripts" / "add_sfx.py"
    result = subprocess.run([sys.executable, str(script), str(source), "--name", "Boom", "--at", "3.5"], capture_output=True,
                            text=True, check=True)
    assert "at_s=3.5" in result.stdout and "none" not in result.stdout
    output = source.with_name(source.stem + "_sfx.mp4")
    probe = subprocess.run([ffmpeg.ffprobe_path(), "-v", "error", "-show_streams", "-of", "json", str(output)],
                           capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout)["streams"]
    assert sorted(stream["codec_type"] for stream in streams) == ["audio", "video"]
    assert ffmpeg.probe(output).duration_s == pytest.approx(6, abs=.1)
    def video_bytes(path):
        return run("-i", str(path), "-map", "0:v:0", "-c:v", "copy", "-f", "h264", "pipe:1").stdout
    assert video_bytes(source) == video_bytes(output)
    assert source.read_bytes() == original and source.stat().st_mtime_ns == stat.st_mtime_ns
    spec = importlib.util.spec_from_file_location("add_sfx", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="overwrite"):
        module.add_sfx(source, source)
    with pytest.raises(ValueError, match="already exists"):
        module.add_sfx(source, output)
    module.add_sfx(source, output, name="Boom", at="3.5", overwrite=True)
    assert video_bytes(source) == video_bytes(output)
    assert source.read_bytes() == original and source.stat().st_mtime_ns == stat.st_mtime_ns
    batch = subprocess.run([sys.executable, str(script), "--dir", str(tmp_path)],
                           capture_output=True, text=True, check=True)
    assert batch.stdout == ""
