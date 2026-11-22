"""Mix one quiet payoff effect into an already rendered clip, copying video."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from autoclip import config
from autoclip.pipeline import export, ffmpeg, sfx, sfx_auto


def add_sfx(source: Path, destination: Path | None = None, *, name: str = "auto",
            at: str = "auto", gain: float = sfx.DEFAULT_GAIN_DB) -> tuple[Path, list[dict]]:
    source = source.resolve()
    destination = (destination or source.with_name(source.stem + "_sfx.mp4")).resolve()
    if destination == source or (destination.exists() and destination.samefile(source)):
        raise ValueError("Output must not overwrite the input")
    if destination.exists():
        raise ValueError(f"Output already exists: {destination}")
    if not math.isfinite(gain):
        raise ValueError("Gain must be finite")
    info = ffmpeg.probe(source)
    if not info.has_audio or not info.has_video:
        raise ValueError("Input must contain video and audio")
    events = []
    if name == "auto" or at == "auto":
        events = sfx_auto.suggest_events(source, 0, info.duration_s, seed=source.stem)
    if name != "auto" and at != "auto":
        events = [{"name": name, "at_s": float(at), "kind": "impact"}]
    if events:
        events[0].update(gain_db=gain)
        if name != "auto":
            events[0]["name"] = name
        if at != "auto":
            events[0]["at_s"] = float(at)
    effects = sfx.prepare_events(events, info.duration_s)
    final_filter = export.build_audio_filtergraph(config.load().export)
    command = [ffmpeg.ffmpeg_path(), "-v", "error", "-n", "-i", str(source)]
    for effect in effects:
        command += ["-i", str(effect.path)]
    if effects:
        graph = sfx.build_filtergraph(effects, first_input=1,
                                     clip_duration_s=info.duration_s, final_filter=final_filter)
        command += ["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]"]
    else:
        command += ["-map", "0:v:0", "-map", "0:a:0", "-af", final_filter]
    command += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart", str(destination)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ffmpeg.FFmpegError("SFX mix failed", command=command, stderr=result.stderr)
    return destination, events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--dir", type=Path)
    parser.add_argument("--name", default="auto")
    parser.add_argument("--at", default="auto")
    parser.add_argument("--gain", type=float, default=sfx.DEFAULT_GAIN_DB)
    args = parser.parse_args()
    if (args.dir is None) == (args.input is None) or (args.dir and args.output):
        parser.error("Supply an input and optional output, or --dir")
    sources = sorted(args.dir.glob("*_9x16.mp4")) if args.dir else [args.input]
    failed = False
    for source in sources:
        if args.dir and source.with_name(source.stem + "_sfx.mp4").exists():
            continue
        try:
            _, events = add_sfx(source, args.output, name=args.name, at=args.at, gain=args.gain)
            effect = events[0] if events else {"name": "none", "at_s": "none"}
            print(f"{source.name}: {effect['name']}, at_s={effect['at_s']}")
        except Exception as exc:
            print(f"{source.name}: error: {exc}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
