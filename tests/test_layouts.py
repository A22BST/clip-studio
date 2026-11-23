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
    assert crop.w * block_h == crop.h * 1080
    assert crop.x <= rect.x and crop.y <= rect.y
    assert crop.x + crop.w >= rect.x + rect.w
    assert crop.y + crop.h >= rect.y + rect.h


def test_plan_json_roundtrip() -> None:
    for layout, fraction in [(Layout.FACECAM, 0.30), (Layout.REACTION, 0.30)]:
        windows = [BlurWindow(0.5, 1.0)]
        plan = default_plan(layout, Rect(0, 0, 200, 150), windows, face_crop=Rect(30, 20, 100, 100))
        assert plan.cam_fraction == plan.seam_y_frac == fraction
        assert LayoutPlan.from_dict(json.loads(json.dumps(plan.to_dict()))) == plan
        windows.clear()
        assert len(plan.blur_windows) == 1


@pytest.mark.parametrize("width,height,expected", [
    (1920, 1080, Rect(1313, 160, 357, 336)),
    (1280, 720, Rect(876, 107, 238, 223)),
])
def test_manual_camera_geometry(width, height, expected):
    geometry = facecam.manual_facecam_geometry((0.684, 0.148, 0.87, 0.459), width, height)
    assert geometry.webcam == geometry.face_crop == expected
    plan = default_plan(Layout.FACECAM, geometry.webcam, exact_camera_crop=True, cam_fraction=0.45)
    assert LayoutPlan.from_dict(json.loads(json.dumps(plan.to_dict()))) == plan


@pytest.mark.parametrize(
    "start,end", [(-1, 2), (2, 1), (1, 1), (0, float("inf")), (float("nan"), 2)]
)
def test_invalid_blur_windows(start: float, end: float) -> None:
    with pytest.raises(ValueError):
        BlurWindow(start, end)


def test_small_overlay_stays_tight_on_720p_source() -> None:
    crop = camera_crop(Rect(20, 20, 320, 240), 1280, 720, 1080, 730)
    assert crop.w < 500 and crop.h < 350


@pytest.mark.parametrize("rect", [Rect(-1, 0, 100, 100), Rect(0, 0, 1921, 1080), Rect(0, 0, 0, 1)])
def test_invalid_camera_geometry_is_explicit(rect: Rect) -> None:
    with pytest.raises(ValueError):
        camera_crop(rect, 1920, 1080, 1080, 1248)


def observation(t: float, cx: float = 160, size: float = 100) -> FaceObservation:
    return FaceObservation(t, cx, 150, size, size, 130, 0.1)


@pytest.fixture
def detector_mocks(monkeypatch: pytest.MonkeyPatch) -> Rect:
    monkeypatch.setattr(ffmpeg, "probe", lambda _: SimpleNamespace(width=1920, height=1080))
    # Expected camera rect for the stable face used below (median face -> expand -> snap).
    return facecam._snap_to_edges(facecam._camera_rect(observation(0), 1920, 1080), 1920, 1080)


def test_stable_small_face(monkeypatch: pytest.MonkeyPatch, detector_mocks: Rect) -> None:
    def sample(_: Path, times: list[float], width: int, height: int) -> list[FaceObservation]:
        assert (len(times), width, height) == (8, 1920, 1080)
        assert times[0] == pytest.approx(12.5) and times[-1] == pytest.approx(19.5)
        return [observation(i) for i in range(8)]

    monkeypatch.setattr(facecam, "_corner_faces", sample)
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
    monkeypatch.setattr(facecam, "_corner_faces", lambda *_, **__: faces)
    assert facecam.detect_facecam(Path("source.mp4"), 0, 8) is None


@pytest.mark.parametrize(
    "error", [FaceDetectionUnavailable("no mediapipe"), ModelDownloadError("offline")]
)
def test_detector_unavailable(
    monkeypatch: pytest.MonkeyPatch, detector_mocks: Rect, error: Exception
) -> None:
    def unavailable(*args: object, **kwargs: object) -> list[FaceObservation]:
        raise error

    monkeypatch.setattr(facecam, "_corner_faces", unavailable)
    assert facecam.detect_facecam(Path("source.mp4"), 0, 8) is None


def test_face_in_the_middle_of_the_frame_is_not_a_facecam(
    monkeypatch: pytest.MonkeyPatch, detector_mocks: Rect
) -> None:
    centre = [observation(i, cx=960) for i in range(8)]
    monkeypatch.setattr(facecam, "_corner_faces", lambda *_, **__: centre)
    assert facecam.detect_facecam(Path("source.mp4"), 0, 8) is None


def test_snap_to_edges_extends_nearly_flush_overlays() -> None:
    assert facecam._snap_to_edges(Rect(30, 40, 300, 250), 1280, 720) == Rect(0, 0, 330, 290)
    assert facecam._snap_to_edges(Rect(500, 300, 300, 250), 1280, 720) == Rect(500, 300, 300, 250)


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
    # Cover-fit uses real source pixels across the entire panel.
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
    assert r"{\an5\pos(540,576)}" in ass
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


@pytest.mark.parametrize(
    "webcam,face",
    [
        (Rect(0, 40, 280, 300), Rect(80, 160, 100, 100)),
        (Rect(1000, 400, 280, 300), Rect(1080, 520, 100, 100)),
        (Rect(0, 0, 400, 300), Rect(100, 90, 100, 100)),
    ],
)
@pytest.mark.parametrize("panel_h", [576, 960, 1248])
def test_webcam_geometry_retains_head_and_fills_panel(
    webcam: Rect, face: Rect, panel_h: int
) -> None:
    clean = facecam.tight_face_crop(face, webcam, face.y + 30)
    crop = camera_crop(clean, 1920, 1080, 1080, panel_h)
    assert crop.w * panel_h == crop.h * 1080
    assert face.x >= crop.x and face.y >= crop.y
    assert face.x + face.w <= crop.x + crop.w
    assert face.y + face.h <= crop.y + crop.h
    assert face.y - crop.y >= crop.h * 0.12
    assert webcam.w / crop.w <= 1.4
    assert webcam.h / crop.h <= 1.4


def test_overlay_removal_is_edge_trimming_without_face_zoom() -> None:
    webcam = Rect(0, 40, 400, 300)
    clean = facecam.trim_webcam_edges(webcam)
    assert clean == Rect(8, 76, 384, 228)
    assert clean.y + clean.h < webcam.y + webcam.h
    assert facecam.tight_face_crop(Rect(100, 150, 100, 100), webcam, 180) == clean
    assert facecam.tight_face_crop(Rect(140, 150, 90, 90), webcam, 180) == clean
    with pytest.raises(ValueError):
        facecam.trim_webcam_edges(webcam, bottom=0.4)


def test_detector_preserves_webcam_context(
    monkeypatch: pytest.MonkeyPatch, detector_mocks: Rect
) -> None:
    monkeypatch.setattr(facecam, "_corner_faces", lambda *args: [observation(i) for i in range(8)])
    geometry = facecam.detect_facecam_geometry(Path("source.mp4"), 0, 8)
    assert geometry is not None
    assert geometry.webcam == detector_mocks
    assert geometry.face_crop == facecam.trim_webcam_edges(geometry.webcam)


@pytest.mark.parametrize("layout", [Layout.FACECAM, Layout.REACTION])
def test_mask_uses_full_webcam_before_gameplay_scaling(layout: Layout) -> None:
    plan = default_plan(layout, Rect(0, 200, 500, 400), face_crop=Rect(50, 250, 150, 140))
    graph = build_layout_filtergraph(plan, src_w=1920, src_h=1080, out_w=1080, out_h=1920)
    crop = camera_crop(plan.face_crop, 1920, 1080, 1080, 576)
    assert f"crop={crop.w}:{crop.h}:{crop.x}:{crop.y}:exact=1" in graph
    assert "pad=" not in graph
    assert "force_original_aspect_ratio=increase" in graph
    assert "[lgsrc]drawbox=x=0:y=200:w=500:h=400:color=black:t=fill,scale=" in graph
    assert default_plan(layout, plan.cam, cam_fraction=0.4).cam_fraction == 0.4


def test_legacy_plan_without_face_crop() -> None:
    plan = LayoutPlan.from_dict(
        {"layout": "facecam", "cam": {"x": 0, "y": 0, "w": 100, "h": 100}, "cam_fraction": 0.38}
    )
    assert plan.face_crop is None
    assert plan.cam_fraction == 0.38


@pytest.mark.parametrize("layout", [Layout.FACECAM, Layout.REACTION])
def test_render_masks_duplicate_camera_and_preserves_logo(layout: Layout) -> None:
    # The central source webcam remains visible in both gameplay cover crops;
    # a missing mask would leave a bright red duplicate in the lower panel.
    plan = default_plan(layout, Rect(240, 60, 160, 180), face_crop=Rect(260, 80, 100, 140))
    graph = build_layout_filtergraph(
        plan, src_w=640, src_h=360, out_w=360, out_h=640, output_label="[vout]"
    )
    graph = export._add_overlay(graph, 360, 640)
    result = subprocess.run(
        [
            ffmpeg.ffmpeg_path(),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=640x360:d=1,drawbox=x=240:y=60:w=160:h=180:color=red:t=fill",
            "-f",
            "lavfi",
            "-i",
            "color=yellow:s=100x40:d=1",
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    pixels = np.frombuffer(result.stdout, dtype=np.uint8).reshape(640, 360, 3)
    seam = round(640 * plan.cam_fraction / 2) * 2
    game = pixels[seam:]
    red = (game[:, :, 0] > 200) & (game[:, :, 1] < 40) & (game[:, :, 2] < 40)
    assert not red.any()
    assert pixels[seam // 2, 180, 0] > 200
    # Logo is applied after composition at x=4%, y=25%, independently of seam.
    logo = pixels[165:185, 20:90]
    assert ((logo[:, :, 0] > 200) & (logo[:, :, 1] > 200) & (logo[:, :, 2] < 40)).mean() > 0.95
