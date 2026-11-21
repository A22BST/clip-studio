"""Optional local payoff effects; audio assets are never distributed with the app."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .. import paths
from . import ffmpeg


class SFXEvent(BaseModel):
    name: str = Field(min_length=1)
    at_s: float = Field(ge=0, allow_inf_nan=False)
    gain_db: float = Field(default=-6, allow_inf_nan=False)
    kind: Literal["impact", "riser"] = "impact"

    model_config = {"extra": "forbid"}


def library_dir() -> Path:
    return paths.root() / "assets" / "sfx"


def _assets() -> list[Path]:
    root = library_dir().resolve()
    return sorted(
        (
            p
            for p in root.rglob("*")
            if p.is_file()
            and p.suffix.casefold() in {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
            and p.resolve().is_relative_to(root)
        ),
        key=lambda p: str(p).casefold(),
    )


def available_names() -> list[str]:
    """List names in the SFX directory, including pack subdirectories."""
    return sorted({p.stem for p in _assets()}, key=str.casefold)


def resolve_name(name: str) -> Path:
    """Resolve a basename with or without extension, never an arbitrary path."""
    matches = [p for p in _assets() if name.casefold() in {p.name.casefold(), p.stem.casefold()}]
    if len(matches) == 1:
        return matches[0].resolve()
    if matches:
        raise ValueError(f"Ambiguous SFX name {name!r} in {library_dir()}")
    raise ValueError(
        f"Unknown SFX {name!r} in {library_dir()}. "
        f"Available names: {', '.join(available_names()) or '(none)'}"
    )


def placement(event: SFXEvent, duration_s: float) -> tuple[float, float]:
    """Return (leading trim, delay); truncate an early riser to retain its ending."""
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError(f"SFX {event.name!r} has no positive finite audio duration")
    start = event.at_s - duration_s if event.kind == "riser" else event.at_s
    return max(0.0, -start), max(0.0, start)


@dataclass(frozen=True)
class PreparedSFX:
    path: Path
    event: SFXEvent
    trim_s: float
    delay_s: float


#: Ahmad (21 Nov 2026): one effect per clip, at the payoff.
MAX_SFX_PER_CLIP = 1


def prepare_events(events: list[SFXEvent | dict], clip_duration_s: float) -> list[PreparedSFX]:
    if len(events) > MAX_SFX_PER_CLIP:
        raise ValueError(f"At most {MAX_SFX_PER_CLIP} SFX event is allowed per clip")
    parsed = [SFXEvent.model_validate(event) for event in events]
    for event in parsed:
        if not 0 <= event.at_s <= clip_duration_s:
            raise ValueError(f"SFX {event.name!r} at_s must be within [0, {clip_duration_s}]")
    prepared = []
    for event in parsed:
        path = resolve_name(event.name)
        info = ffmpeg.probe(path)
        if not info.has_audio:
            raise ValueError(f"SFX {event.name!r} has no audio stream")
        trim, delay = placement(event, info.duration_s)
        prepared.append(PreparedSFX(path, event, trim, delay))
    return prepared


def build_filtergraph(
    effects: list[PreparedSFX],
    *,
    first_input: int,
    clip_duration_s: float,
    final_filter: str,
    stream_filter: str = "",
) -> str:
    """Mix effects at an additional -12 dB, then normalize the complete mix.

    Default effective gain is -18 dB. Profanity filters affect only the stream.
    """
    parts = [
        f"[0:a]{stream_filter + ',' if stream_filter else ''}"
        "aformat=sample_rates=48000:channel_layouts=stereo[main]"
    ]
    for i, effect in enumerate(effects):
        parts.append(
            f"[{first_input + i}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"atrim=start={effect.trim_s:.4f},asetpts=PTS-STARTPTS,"
            f"volume={effect.event.gain_db - 12:.4f}dB,"
            f"adelay={effect.delay_s * 1000:.4f}:all=1,apad,"
            f"atrim=duration={clip_duration_s:.4f}[sfx{i}]"
        )
    labels = "[main]" + "".join(f"[sfx{i}]" for i in range(len(effects)))
    parts.append(
        f"{labels}amix=inputs={len(effects) + 1}:duration=first:normalize=0,{final_filter}[aout]"
    )
    return ";".join(parts)
