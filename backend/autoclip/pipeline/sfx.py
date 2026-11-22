"""Optional local payoff effects; audio assets are never distributed with the app."""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .. import paths
from . import ffmpeg

DEFAULT_GAIN_DB = 0
TARGET_PEAK_DB = -2
#: Short percussive effects have a huge crest factor, so a peak target leaves them far quieter than
#: speech. Level them by average loudness instead and let the limiter catch the transients.
TARGET_RMS_DB = -8


class SFXEvent(BaseModel):
    name: str = Field(min_length=1)
    at_s: float = Field(ge=0, allow_inf_nan=False)
    gain_db: float = Field(default=DEFAULT_GAIN_DB, allow_inf_nan=False)
    kind: Literal["impact", "riser"] = "impact"

    model_config = {"extra": "forbid"}


@lru_cache(maxsize=128)
def _measure_peak(path: Path, mtime_ns: int) -> float:
    """Cache astats measurements by resolved asset path and modification time."""
    command = [ffmpeg.ffmpeg_path(), "-hide_banner", "-nostats", "-i", str(path),
               "-vn", "-af", "aformat=sample_rates=48000:channel_layouts=stereo,astats=reset=0",
               "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ffmpeg.FFmpegError("Could not measure SFX peak", command=command,
                                 stderr=result.stderr)
    levels = [float(value) for value in re.findall(r"Peak level dB: ([^\s]+)", result.stderr)]
    peak = max(levels, default=float("nan"))
    if not math.isfinite(peak):
        raise ValueError(f"SFX {path.name!r} has no finite audio peak")
    return peak


@lru_cache(maxsize=128)
def _measure_rms(path: Path, mtime_ns: int) -> float:
    command = [ffmpeg.ffmpeg_path(), "-hide_banner", "-nostats", "-i", str(path),
               "-vn", "-af", "aformat=sample_rates=48000:channel_layouts=stereo,astats=reset=0",
               "-f", "null", "-"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ffmpeg.FFmpegError("Could not measure SFX loudness", command=command,
                                 stderr=result.stderr)
    levels = [float(v) for v in re.findall(r"RMS level dB: ([^\s]+)", result.stderr)
              if v not in ("-inf", "nan")]
    if not levels:
        raise ValueError(f"SFX {path.name!r} has no finite loudness")
    return levels[-1]  # the 'Overall' line is printed last


def measure_rms(path: Path) -> float:
    path = path.resolve()
    return _measure_rms(path, path.stat().st_mtime_ns)


def measure_peak(path: Path) -> float:
    path = path.resolve()
    return _measure_peak(path, path.stat().st_mtime_ns)


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
    duration_s: float
    peak_db: float | None = None


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
        prepared.append(PreparedSFX(path, event, trim, delay, info.duration_s))
    return prepared


def build_filtergraph(
    effects: list[PreparedSFX],
    *,
    first_input: int,
    clip_duration_s: float,
    final_filter: str,
    stream_filter: str = "",
) -> str:
    """Peak-normalize accents, duck only their windows, and normalize the mix."""
    stream_chain = [stream_filter] if stream_filter else []
    stream_chain.append("aformat=sample_rates=48000:channel_layouts=stereo")
    for effect in effects:
        start = effect.delay_s
        end = min(clip_duration_s, start + effect.duration_s - effect.trim_s)
        if end <= start:
            continue
        # Ramps remain inside the effect window, including truncated early risers.
        stream_chain.append(
            f"volume='1-(1-0.354813)*max(0,min(1,min((t-{start:.4f})/0.08,"
            f"({end:.4f}-t)/0.08)))':eval=frame:"
            f"enable='between(t,{start:.4f},{end:.4f})'"
        )
    parts = ["[0:a]" + ",".join(stream_chain) + "[main]"]
    for i, effect in enumerate(effects):
        rms_db = measure_rms(effect.path)
        parts.append(
            f"[{first_input + i}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"atrim=start={effect.trim_s:.4f},asetpts=PTS-STARTPTS,"
            f"volume={TARGET_RMS_DB - rms_db + effect.event.gain_db:.4f}dB,"
            f"alimiter=limit=0.9:attack=1:release=30:level=0,"
            f"adelay={effect.delay_s * 1000:.4f}:all=1,apad,"
            f"atrim=duration={clip_duration_s:.4f}[sfx{i}]"
        )
    labels = "[main]" + "".join(f"[sfx{i}]" for i in range(len(effects)))
    parts.append(
        f"{labels}amix=inputs={len(effects) + 1}:duration=first:normalize=0,"
        f"alimiter=limit=0.95:level=0:latency=1,{final_filter}[aout]"
    )
    return ";".join(parts)
