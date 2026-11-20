"""Compose portrait blocks without distorting faces or blurring the camera."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Layout(StrEnum):
    TRACK = "track"
    FACECAM = "facecam"
    REACTION = "reaction"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class BlurWindow:
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.start_s) and math.isfinite(self.end_s)):
            raise ValueError("Blur window times must be finite.")
        if self.start_s < 0 or self.end_s <= self.start_s:
            raise ValueError("Blur windows require 0 <= start_s < end_s.")


@dataclass
class LayoutPlan:
    layout: Layout
    cam: Rect | None
    cam_fraction: float
    blur_windows: list[BlurWindow] = field(default_factory=list)

    @property
    def seam_y_frac(self) -> float:
        return self.cam_fraction

    def to_dict(self) -> dict[str, Any]:
        """Use plain values so saved plans survive JSON round trips."""
        return {**asdict(self), "layout": self.layout.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LayoutPlan:
        return cls(
            layout=Layout(data["layout"]),
            cam=Rect(**data["cam"]) if data.get("cam") is not None else None,
            cam_fraction=float(data["cam_fraction"]),
            blur_windows=[BlurWindow(**window) for window in data.get("blur_windows", [])],
        )


def default_plan(
    layout: Layout, cam: Rect | None, blur_windows: list[BlurWindow] | None = None
) -> LayoutPlan:
    return LayoutPlan(
        layout, cam, 0.65 if layout == Layout.REACTION else 0.38, list(blur_windows or [])
    )


def camera_crop(rect: Rect, src_w: int, src_h: int, block_w: int, block_h: int) -> Rect:
    """Expand rather than squeeze a camera box, retaining 10% face headroom.

    Round outward to source pixels; the render chain removes any subpixel
    aspect discrepancy with a cover crop instead of stretching the image.
    Exact integer aspect multiples can expand a tiny overlay to nearly the
    whole source, so they would defeat the purpose of isolating the camera.
    At source edges the margin is clipped, but the original box is never cut.
    """
    if min(src_w, src_h, block_w, block_h, rect.w, rect.h) <= 0:
        raise ValueError("Frame, block and camera dimensions must be positive.")
    if rect.x < 0 or rect.y < 0 or rect.x + rect.w > src_w or rect.y + rect.h > src_h:
        raise ValueError("Camera rectangle must be inside the source frame.")
    left = max(0, math.floor(rect.x - rect.w * 0.1))
    top = max(0, math.floor(rect.y - rect.h * 0.1))
    right = min(src_w, math.ceil(rect.x + rect.w * 1.1))
    bottom = min(src_h, math.ceil(rect.y + rect.h * 1.1))
    aspect = block_w / block_h
    width = math.ceil(max(right - left, (bottom - top) * aspect))
    height = math.ceil(max(bottom - top, (right - left) / aspect))
    if width > src_w or height > src_h:
        raise ValueError("Camera plus margin cannot fit the block aspect inside the source.")
    x = max(0, min(src_w - width, round((left + right - width) / 2)))
    y = max(0, min(src_h - height, round((top + bottom - height) / 2)))
    return Rect(x, y, width, height)


def build_layout_filtergraph(
    plan: LayoutPlan,
    *,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    input_label: str = "[0:v]",
    output_label: str = "[vlay]",
) -> str:
    """Reset timestamps so spoiler windows refer to the exported clip only."""
    if plan.layout == Layout.TRACK or plan.cam is None:
        raise ValueError("A camera layout requires a camera rectangle; use TRACK otherwise.")
    if not math.isfinite(plan.cam_fraction) or not 0 < plan.cam_fraction < 1:
        raise ValueError("cam_fraction must be between zero and one.")
    if min(out_w, out_h) < 4 or out_w % 2 or out_h % 2:
        raise ValueError("Layout output dimensions must be positive even dimensions.")
    cam_h = max(2, min(out_h - 2, round(out_h * plan.cam_fraction / 2) * 2))
    game_h = out_h - cam_h
    cam = camera_crop(plan.cam, src_w, src_h, out_w, cam_h)
    parts = [
        f"{input_label}setpts=PTS-STARTPTS,split=2[lcsrc][lgsrc]",
        f"[lcsrc]crop={cam.w}:{cam.h}:{cam.x}:{cam.y}:exact=1,"
        f"scale={out_w}:{cam_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={out_w}:{cam_h},setsar=1[lc]",
        f"[lgsrc]scale={out_w}:{game_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{game_h},setsar=1[lg]",
    ]
    game = "[lg]"
    if plan.blur_windows:
        enable = "+".join(f"between(t,{w.start_s:.6f},{w.end_s:.6f})" for w in plan.blur_windows)
        parts.extend(
            [
                "[lg]split=2[lsharp][lblurin]",
                # Tiny downsampling destroys readable details before the final blur.
                f"[lblurin]scale=16:16,scale={out_w}:{game_h},gblur=sigma=40[lblur]",
                f"[lsharp][lblur]overlay=enable='{enable}'[lgame]",
            ]
        )
        game = "[lgame]"
    parts.append(f"[lc]{game}vstack=inputs=2,setsar=1,format=yuv420p{output_label}")
    return ";".join(parts)
