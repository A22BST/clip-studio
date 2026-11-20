"""Conservative overlay detection keeps gameplay faces out of camera layouts."""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np

from ..models import ModelDownloadError
from . import ffmpeg
from .layouts import Rect
from .reframe.faces import FaceDetectionUnavailable, FaceObservation

log = logging.getLogger(__name__)


def _camera_rect(face: FaceObservation, width: int, height: int) -> Rect:
    """Include shoulders and a likely overlay border, not just facial landmarks."""
    w = min(width, math.ceil(face.width * 2.4))
    h = min(height, math.ceil(face.height * 2.3))
    return Rect(
        max(0, min(width - w, round(face.cx - w / 2))),
        max(0, min(height - h, round(face.cy - h * 0.55))),
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


def detect_facecam(source: Path, start_s: float, end_s: float, *, samples: int = 8) -> Rect | None:
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
            # Median position/size (robust to a leaning head), then expand to shoulders + border.
            typical = FaceObservation(
                0,
                _median([f.cx for f in matches]),
                _median([f.cy for f in matches]),
                _median([f.width for f in matches]),
                _median([f.height for f in matches]),
                0,
                0,
            )
            if not (typical.cx < width * 0.45 or typical.cx > width * 0.55):
                continue  # an overlay hugs the left or right edge; centred faces are the subject
            rect = _camera_rect(typical, width, height)
            if rect.w * rect.h >= width * height * 0.45:
                continue
            return _snap_to_edges(rect, width, height)
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
