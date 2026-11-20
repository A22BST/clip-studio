"""Check actual pixels so valid-looking graphs cannot hide swapped or blurred blocks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from autoclip.config import ExportSettings
from autoclip.models import ModelDownloadError
from autoclip.pipeline import captions, export, facecam, ffmpeg
from autoclip.pipeline.layouts import (
    BlurWindow,
    Layout,
    LayoutPlan,
    Rect,
    build_layout_filtergraph,
    camera_crop,
    default_plan,
)
from autoclip.pipeline.reframe.croppath import centre_crop
from autoclip.pipeline.reframe.faces import FaceDetectionUnavailable, FaceObservation
from autoclip.pipeline.transcript import Word


@pytest.mark.parametrize(
    "rect",
    [
        Rect(30, 30, 150, 120),
        Rect(1700, 900, 180, 130),
        Rect(0, 0, 100, 100),
        Rect(1820, 980, 100, 100),
        Rect(800, 450, 150, 120),
    ],
)
@pytest.mark.parametrize("block_h", [730, 1248, 960])
def test_camera_geometry(rect: Rect, block_h: int) -> None:
    crop = camera_crop(rect, 1920, 1080, 1080, block_h)
    assert crop.x >= 0 and crop.y >= 0
    assert crop.x + crop.w <= 1920 and crop.y + crop.h <= 1080
    assert abs(crop.w - crop.h * 1080 / block_h) <= max(1, 1080 / block_h)
    assert crop.x <= max(0, rect.x - rect.w * 0.1)
    assert crop.y <= max(0, rect.y - rect.h * 0.1)
    assert crop.x + crop.w >= min(1920, rect.x + rect.w * 1.1)
    assert crop.y + crop.h >= min(1080, rect.y + rect.h * 1.1)


def test_plan_json_roundtrip() -> None:
    for layout, fraction in [(Layout.FACECAM, 0.38), (Layout.REACTION, 0.65)]:
        windows = [BlurWindow(0.5, 1.0)]
        plan = default_plan(layout, Rect(0, 0, 200, 150), windows)
        assert plan.cam_fraction == plan.seam_y_frac == fraction
        assert LayoutPlan.from_dict(json.loads(json.dumps(plan.to_dict()))) == plan
        windows.clear()
        assert len(plan.blur_windows) == 1


@pytest.mark.parametrize(
    "start,end", [(-1, 2), (2, 1), (1, 1), (0, float("inf")), (float("nan"), 2)]
)
def test_invalid_blur_windows(start: float, end: float) -> None:
    with pytest.raises(ValueError):
        BlurWindow(start, end)


def test_small_overlay_stays_tight_on_720p_source() -> None:
    crop = camera_crop(Rect(20, 20, 320, 240), 1280, 720, 1080, 730)
    assert crop.w < 500 and crop.h < 350


def test_impossible_camera_geometry_is_explicit() -> None:
    with pytest.raises(ValueError, match="cannot fit"):
        camera_crop(Rect(0, 0, 1920, 1080), 1920, 1080, 1080, 1248)


def observation(t: float, cx: float = 160, size: float = 100) -> FaceObservation:
    return FaceObservation(t, cx, 150, size, size, 130, 0.1)


@pytest.fixture
def detector_mocks(monkeypatch: pytest.MonkeyPatch) -> Rect:
    monkeypatch.setattr(ffmpeg, "probe", lambda _: SimpleNamespace(width=1920, height=1080))
    rect = Rect(40, 64, 240, 200)
    rng = np.random.default_rng(42)
    frames = [rng.integers(0, 256, (1080, 1920), dtype=np.uint8) for _ in range(8)]
    for frame in frames:
        frame[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w] = 80
    monkeypatch.setattr(facecam, "_sample_frames", lambda *_: frames)
    return rect


def test_stable_small_face(monkeypatch: pytest.MonkeyPatch, detector_mocks: Rect) -> None:
    def sample(_: Path, **kwargs: float) -> list[FaceObservation]:
        assert kwargs == {"start_s": 12, "end_s": 20, "sample_fps": 1}
        return [observation(i) for i in range(8)]

    monkeypatch.setattr(facecam, "sample_faces", sample)
    assert facecam.detect_facecam(Path("source.mp4"), 12, 20) == detector_mocks


@pytest.mark.parametrize("kind", ["none", "huge", "wander", "minority", "duplicates"])
def test_reject_uncertain_faces(
    monkeypatch: pytest.MonkeyPatch, detector_mocks: Rect, kind: str
) -> None:
    faces = {
        "none": [],
        "huge": [observation(i, 960, 900) for i in range(8)],
        "wander": [observation(i, 160 + i * 180) for i in range(8)],
        "minority": [observation(i) for i in range(4)],
        "duplicates": [observation(0) for _ in range(8)],
    }[kind]
    monkeypatch.setattr(facecam, "sample_faces", lambda *_, **__: faces)
    assert facecam.detect_facecam(Path("source.mp4"), 0, 8) is None


@pytest.mark.parametrize(
    "error", [FaceDetectionUnavailable("no mediapipe"), ModelDownloadError("offline")]
)
def test_detector_unavailable(
    monkeypatch: pytest.MonkeyPatch, detector_mocks: Rect, error: Exception
) -> None:
    def unavailable(*args: object, **kwargs: object) -> list[FaceObservation]:
        raise error

    monkeypatch.setattr(facecam, "sample_faces", unavailable)
    assert facecam.detect_facecam(Path("source.mp4"), 0, 8) is None


def test_moving_border_and_static_scene_are_rejected(detector_mocks: Rect) -> None:
    rng = np.random.default_rng(4)
    frames = [rng.integers(0, 256, (1080, 1920), dtype=np.uint8) for _ in range(3)]
    assert not facecam._static_border(frames, detector_mocks)
    assert not facecam._static_border([frames[0]] * 3, detector_mocks)


@pytest.fixture(scope="module")
def layout_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("layout-media") / "source.mp4"
    subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1920x1080:rate=12:duration=2,"
            "drawbox=x=0:y=0:w=700:h=500:color=red:t=fill,"
            "drawbox=x=200:y=200:w=20:h=20:color=white:t=fill",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def make_request(source: Path, destination: Path, plan: LayoutPlan | None) -> export.ExportRequest:
    return export.ExportRequest(
        source,
        destination,
        0.25,
        1.75,
        centre_crop(1920, 1080, 1.5),
        [Word("seam", 0.25, 1.5)],
        captions.get_style("bold_pop"),
        layout_plan=plan,
        burn_captions=False,
    )


def read_frame(source: Path, t: float) -> np.ndarray:
    result = subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-v",
            "error",
            "-ss",
            str(t),
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(1920, 1080, 3)


def sharpness(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


@pytest.mark.slow
@pytest.mark.parametrize("layout", [Layout.FACECAM, Layout.REACTION])
def test_real_layout_pixels(layout_source: Path, tmp_path: Path, layout: Layout) -> None:
    plan = default_plan(
        layout,
        Rect(100, 100, 200, 150),
        [BlurWindow(0.35, 0.75)] if layout == Layout.REACTION else [],
    )
    destination = tmp_path / "layout.mp4"
    request = make_request(layout_source, destination, plan)
    export.export_clip(
        request, work_dir=tmp_path / "work", settings=ExportSettings(prefer_hardware_encoder=False)
    )
    info = ffmpeg.probe(destination)
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio
    assert info.duration_s == pytest.approx(1.5, abs=0.1)
    outside, inside, after = [read_frame(destination, t) for t in (0.15, 0.5, 1.1)]
    seam = round(1920 * plan.cam_fraction / 2) * 2
    camera = outside[:seam]
    red = (camera[:, :, 0] > 200) & (camera[:, :, 1] < 40) & (camera[:, :, 2] < 40)
    assert red.mean() > 0.95
    assert outside[seam + 20 :].std() > 50
    if layout == Layout.REACTION:
        assert sharpness(inside[seam + 10 :]) < sharpness(outside[seam + 10 :]) * 0.05
        assert sharpness(inside[seam + 10 :]) < sharpness(after[seam + 10 :]) * 0.05
        assert (inside[: seam - 5].min(axis=2) > 220).mean() > 0.001
        assert sharpness(inside[: seam - 5]) > 0.1
        assert sharpness(inside[: seam - 5]) == pytest.approx(
            sharpness(outside[: seam - 5]), rel=0.1
        )
        assert sharpness(after[: seam - 5]) == pytest.approx(
            sharpness(outside[: seam - 5]), rel=0.1
        )


@pytest.mark.slow
def test_layout_captions_centre_on_seam(layout_source: Path, tmp_path: Path) -> None:
    plan = default_plan(Layout.FACECAM, Rect(100, 100, 200, 150))
    request = make_request(layout_source, tmp_path / "captions.mp4", plan)
    request.burn_captions = True
    export.export_clip(
        request, work_dir=tmp_path / "work", settings=ExportSettings(prefer_hardware_encoder=False)
    )
    ass = (tmp_path / "work" / "captions" / "captions.ass").read_text(encoding="utf-8")
    assert r"{\an5\pos(540,730)}" in ass
    assert export.build_video_filtergraph(request, subtitle_name="captions.ass").endswith(
        "[vlay]ass=filename=captions.ass:fontsdir=fonts[vout]"
    )


def test_track_fallback_and_ratio_rejection(tmp_path: Path) -> None:
    request = make_request(Path("missing.mp4"), tmp_path / "out.mp4", None)
    original = export.build_video_filtergraph(request, subtitle_name="captions.ass")
    for plan in [default_plan(Layout.FACECAM, None), default_plan(Layout.TRACK, None)]:
        request.layout_plan = plan
        assert export.build_video_filtergraph(request, subtitle_name="captions.ass") == original
    request.layout_plan = default_plan(Layout.FACECAM, Rect(0, 0, 100, 100))
    request.ratio = "1:1"
    with pytest.raises(export.ExportError, match="9:16"):
        export.build_video_filtergraph(request, subtitle_name=None)


def test_custom_labels_and_fraction() -> None:
    plan = LayoutPlan(Layout.FACECAM, Rect(50, 50, 100, 100), 0.5)
    graph = build_layout_filtergraph(
        plan,
        src_w=1920,
        src_h=1080,
        out_w=1080,
        out_h=1920,
        input_label="[input]",
        output_label="[done]",
    )
    assert graph.startswith("[input]") and graph.endswith("[done]")
    assert "scale=1080:960" in graph
