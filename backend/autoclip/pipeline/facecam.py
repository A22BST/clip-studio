"""Conservative overlay detection keeps gameplay faces out of camera layouts."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..models import ModelDownloadError
from . import ffmpeg
from .layouts import Rect
from .reframe.faces import FaceDetectionUnavailable, FaceObservation

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FacecamGeometry:
    webcam: Rect
    face_crop: Rect


def manual_facecam_geometry(
    box: tuple[float, float, float, float], width: int, height: int
) -> FacecamGeometry:
    """Convert fixed frame fractions to pixels without detector edge trimming."""
    x0, y0, x1, y1 = box
    if width <= 0 or height <= 0 or not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("Invalid manual camera bounds or frame dimensions.")
    left, top, right, bottom = round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height)
    if right <= left or bottom <= top:
        raise ValueError("Manual camera box must cover at least one pixel.")
    rect = Rect(left, top, right - left, bottom - top)
    return FacecamGeometry(rect, rect)


def trim_webcam_edges(
    webcam: Rect,
    *,
    left: float = 0.02,
    top: float = 0.12,
    right: float = 0.02,
    bottom: float = 0.12,
) -> Rect:
    """Remove border/counter strips, independently of face position or size."""
    margins = (left, top, right, bottom)
    if (
        min(webcam.w, webcam.h) <= 0
        or any(not math.isfinite(v) or v < 0 for v in margins)
        or left + right >= 1
        or top + bottom >= 1
    ):
        raise ValueError("Invalid webcam edge trims.")
    x = webcam.x + math.floor(webcam.w * left)
    y = webcam.y + math.floor(webcam.h * top)
    end_x = webcam.x + webcam.w - math.floor(webcam.w * right)
    end_y = webcam.y + webcam.h - math.floor(webcam.h * bottom)
    if end_x - x < webcam.w / 1.4 or end_y - y < webcam.h / 1.4:
        raise ValueError("Edge trims must retain at least 1/1.4 of each dimension.")
    return Rect(x, y, end_x - x, end_y - y)


def tight_face_crop(face: Rect, webcam: Rect, eye_y: float) -> Rect:
    """Compatibility name: retain the webcam, trimming only overlay edges.

    Facial landmarks exclude hair and hats. Reserve generous space above them
    rather than deriving a zoomed portrait from the eye line.
    """
    crop = trim_webcam_edges(webcam)
    if not math.isfinite(eye_y) or not face.y <= eye_y <= face.y + face.h:
        raise ValueError("Eyes must be inside the face.")
    if min(face.w, face.h) <= 0 or not (
        crop.x <= face.x
        and crop.y <= face.y
        and face.x + face.w <= crop.x + crop.w
        and face.y + face.h <= crop.y + crop.h
        and face.y - crop.y >= crop.h * 0.12
    ):
        raise ValueError("Trimmed webcam cannot retain the face and headroom.")
    return crop


def _camera_rect(face: FaceObservation, width: int, height: int) -> Rect:
    """Include shoulders and a likely overlay border, not just facial landmarks."""
    w = min(width, math.ceil(face.width * 2.8))
    h = min(height, math.ceil(face.height * 3.0))
    return Rect(
        max(0, min(width - w, round(face.cx - w / 2))),
        max(0, min(height - h, round(face.cy - h * 0.57))),
        w,
        h,
    )


#: Edge crops (fraction of frame width, height) tried in order. Facecams are small and sit against
#: the left or right edge (corner or mid-height), and MediaPipe's face model shrinks its input to
#: ~192 px: scanning the whole 720p frame turns a 120 px webcam face into ~18 px and finds nothing.
#: Cropping the edge strips (top / middle / bottom, both sides) keeps such faces detectable.
_CORNER_SCALES = ((0.30, 0.40), (0.42, 0.52))


def _corner_faces(source: Path, times: list[float], width: int, height: int):
    """Detect faces inside the four frame corners; returns observations in full-frame pixels.

    ``t`` is the offset from the first sample time so slots line up with ``detect_facecam``.
    """
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, RunningMode
    except ImportError as exc:
        raise FaceDetectionUnavailable(f"MediaPipe or OpenCV is unavailable: {exc}") from exc
    from .. import models
    from .reframe.faces import _to_observation

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(models.ensure("face_landmarker"))),
        running_mode=RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=0.4,
    )
    capture = cv2.VideoCapture(str(source))
    observations: list[FaceObservation] = []
    try:
        with FaceLandmarker.create_from_options(options) as landmarker:
            for timestamp in times:
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                ok, frame = capture.read()
                if not ok:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                for left in (True, False):
                    for vertical in (0.0, 0.5, 1.0):  # top, middle, bottom of the edge
                        for fw, fh in _CORNER_SCALES:
                            cw, ch = round(width * fw), round(height * fh)
                            x0 = 0 if left else width - cw
                            y0 = round((height - ch) * vertical)
                            crop = np.ascontiguousarray(rgb[y0 : y0 + ch, x0 : x0 + cw])
                            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)
                            found = False
                            for landmarks in landmarker.detect(image).face_landmarks or []:
                                obs = _to_observation(landmarks, timestamp - times[0], cw, ch)
                                if obs is not None:
                                    obs.cx += x0
                                    obs.cy += y0
                                    obs.eye_y += y0
                                    observations.append(obs)
                                    found = True
                            if found:
                                break  # a tighter crop found it; skip the wider one
    finally:
        capture.release()
    return observations


#: A webcam overlay is small. Bigger faces are the main subject (IRL stream, full-screen cam).
MAX_FACE_WIDTH_FRAC = 0.22


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def detect_facecam_geometry(
    source: Path, start_s: float, end_s: float, *, samples: int = 8
) -> FacecamGeometry | None:
    """Find a webcam overlay tucked in a frame corner, or None (the caller then uses TRACK).

    Evidence required: a face that stays put (same spot and size) in more than half of the
    samples, is small relative to the frame, and sits in a corner region. A face that moves,
    is large, or is seen only now and then (an NPC walking past) is not a facecam.
    """
    if samples < 3 or start_s < 0 or end_s <= start_s:
        return None
    try:
        info = ffmpeg.probe(source)
        if not info.width or not info.height:
            return None
        width, height = info.width, info.height
        step = (end_s - start_s) / samples
        times = [start_s + (i + 0.5) * step for i in range(samples)]
        faces = _corner_faces(source, times, width, height)
        for seed in faces:
            if seed.width > width * MAX_FACE_WIDTH_FRAC:
                continue
            matches = [
                face
                for face in faces
                if abs(face.cx - seed.cx) < seed.width * 0.35
                and abs(face.cy - seed.cy) < seed.height * 0.35
                and 0.65 < face.width / seed.width < 1.5
                and 0.65 < face.height / seed.height < 1.5
            ]
            # Several faces in one frame must not count as several pieces of persistence.
            slots = {round(face.t / step) for face in matches if 0 <= face.t < end_s - start_s}
            if len(slots) <= samples / 2:
                continue
            # Keep separate display and exclusion rectangles: the gameplay mask needs
            # the whole overlay, while the camera panel trims only overlay edges.
            typical = FaceObservation(
                0,
                _median([f.cx for f in matches]),
                _median([f.cy for f in matches]),
                _median([f.width for f in matches]),
                _median([f.height for f in matches]),
                _median([f.eye_y for f in matches]),
                0,
            )
            if not (typical.cx < width * 0.45 or typical.cx > width * 0.55):
                continue  # an overlay hugs the left or right edge; centred faces are the subject
            rect = _camera_rect(typical, width, height)
            if rect.w * rect.h >= width * height * 0.45:
                continue
            webcam = _snap_to_edges(rect, width, height)
            face_box = Rect(
                max(webcam.x, math.floor(typical.left)),
                max(webcam.y, math.floor(typical.top)),
                math.ceil(typical.right) - max(webcam.x, math.floor(typical.left)),
                math.ceil(typical.bottom) - max(webcam.y, math.floor(typical.top)),
            )
            return FacecamGeometry(webcam, tight_face_crop(face_box, webcam, typical.eye_y))
    except (
        FaceDetectionUnavailable,
        ModelDownloadError,
        ffmpeg.FFmpegError,
        ImportError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        log.warning("Facecam detection unavailable for %s: %s", source.name, exc)
    return None


def detect_facecam(source: Path, start_s: float, end_s: float, *, samples: int = 8) -> Rect | None:
    """Compatibility API returning the full webcam exclusion rectangle."""
    geometry = detect_facecam_geometry(source, start_s, end_s, samples=samples)
    return geometry.webcam if geometry is not None else None


def _snap_to_edges(rect: Rect, width: int, height: int) -> Rect:
    """Overlays sit flush against a frame edge; extend a nearly-flush rect to the edge so no
    sliver of gameplay is included between the overlay and the border."""
    margin_x, margin_y = round(width * 0.06), round(height * 0.08)
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    if x <= margin_x:
        w, x = w + x, 0
    elif x + w >= width - margin_x:
        w = width - x
    if y <= margin_y:
        h, y = h + y, 0
    elif y + h >= height - margin_y:
        h = height - y
    return Rect(x, y, w, h)
