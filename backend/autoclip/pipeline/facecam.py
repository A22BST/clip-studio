"""Conservative overlay detection keeps gameplay faces out of camera layouts."""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np

from ..models import ModelDownloadError
from . import ffmpeg
from .layouts import Rect
from .reframe.faces import FaceDetectionUnavailable, FaceObservation, sample_faces

log = logging.getLogger(__name__)


def _camera_rect(face: FaceObservation, width: int, height: int) -> Rect:
    """Include shoulders and a likely overlay border, not just facial landmarks."""
    w = min(width, math.ceil(face.width * 2.4))
    h = min(height, math.ceil(face.height * 2.0))
    return Rect(
        max(0, min(width - w, round(face.cx - w / 2))),
        max(0, min(height - h, round(face.cy - h * 0.43))),
        w,
        h,
    )


def _sample_frames(source: Path, times: list[float]) -> list[np.ndarray]:
    """Seek only the requested frames to bound decoding and memory costs."""
    import cv2

    capture = cv2.VideoCapture(str(source))
    frames = []
    try:
        for timestamp in times:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok:
                return []
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    finally:
        capture.release()
    return frames


def _static_border(frames: list[np.ndarray], rect: Rect) -> bool:
    """Demand temporal evidence: static whole scenes cannot prove an overlay."""
    if len(frames) < 3:
        return False
    height, width = frames[0].shape
    border = np.zeros((height, width), dtype=bool)
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    thickness = max(2, round(min(w, h) * 0.05))
    border[y : y + h, x : x + w] = True
    border[y + thickness : y + h - thickness, x + thickness : x + w - thickness] = False
    outside = np.ones_like(border)
    outside[y : y + h, x : x + w] = False
    if not border.any() or not outside.any():
        return False
    changes = [
        np.abs(b.astype(np.float32) - a.astype(np.float32))
        for a, b in zip(frames, frames[1:], strict=False)
    ]
    edge_change = float(np.mean([delta[border].mean() for delta in changes]))
    scene_change = float(np.mean([delta[outside].mean() for delta in changes]))
    return scene_change > 3 and edge_change < min(12, scene_change * 0.4)


def detect_facecam(source: Path, start_s: float, end_s: float, *, samples: int = 8) -> Rect | None:
    """Prefer TRACK when size, persistence or a static border cannot be proven."""
    if samples < 3 or start_s < 0 or end_s <= start_s:
        return None
    try:
        info = ffmpeg.probe(source)
        if not info.width or not info.height:
            return None
        width, height = info.width, info.height
        step = (end_s - start_s) / samples
        faces = sample_faces(source, start_s=start_s, end_s=end_s, sample_fps=1 / step)
        # Match each seed across sample slots, allowing misses but never counting
        # multiple faces in one frame as multiple pieces of persistence evidence.
        for seed in faces:
            rect = _camera_rect(seed, width, height)
            if rect.w * rect.h >= width * height * 0.45:
                continue
            matches = [
                face
                for face in faces
                if abs(face.cx - seed.cx) < seed.width * 0.35
                and abs(face.cy - seed.cy) < seed.height * 0.35
                and 0.65 < face.width / seed.width < 1.5
                and 0.65 < face.height / seed.height < 1.5
            ]
            slots = {round(face.t / step) for face in matches if 0 <= face.t < end_s - start_s}
            if len(slots) <= samples / 2:
                continue
            # Union of accepted observations avoids clipping a slightly moving head.
            left = min(face.left for face in matches)
            right = max(face.right for face in matches)
            top = min(face.top for face in matches)
            bottom = max(face.bottom for face in matches)
            union = FaceObservation(
                0, (left + right) / 2, (top + bottom) / 2, right - left, bottom - top, 0, 0
            )
            rect = _camera_rect(union, width, height)
            if rect.w * rect.h >= width * height * 0.45:
                continue
            frames = _sample_frames(source, [start_s + i * step for i in range(samples)])
            if _static_border(frames, rect):
                return rect
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
