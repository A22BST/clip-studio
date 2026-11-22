"""Deterministic payoff detection using only short-time audio loudness."""

from __future__ import annotations

import hashlib
import math
import subprocess
from pathlib import Path

import numpy as np

from . import ffmpeg, sfx

PREFERENCES = (
    "Boom", "MEME BOOM", "BONE CRACK", "Pop", "Bang", "FAH", "PEW",
    "CHA CHING", "DING", "GLITTER", "MAGIC REVEAL", "Camera flash",
    "Intro sound (correct)", "RIZZ", "PIANO MEME", "SPONGEBOB", "AMONG US", "ROBLOX",
)


def suggest_events(
    audio_path_or_wav: str | Path, start_s: float, end_s: float, seed: str,
) -> list[dict]:
    """Decode a source window; return one clip-relative impact, or no clear peak.

    RMS frames and hops are 50 ms; each frame is compared with the preceding
    1.5 seconds. The first threshold crossing leading to the strongest rise is
    the onset, rather than the middle of a sustained loud passage.
    """
    if not all(math.isfinite(t) for t in (start_s, end_s)) or start_s < 0 or end_s <= start_s:
        raise ValueError("Expected a finite positive source window")
    duration = end_s - start_s
    lo, hi = max(3.0, duration * .25), min(duration - 1.5, duration * .85)
    if lo > hi:
        return []
    names = {name.casefold(): name for name in sfx.available_names()}
    index = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest(), "big") % len(PREFERENCES)
    name = next((names[p.casefold()] for p in
                 (PREFERENCES[(index + i) % len(PREFERENCES)] for i in range(len(PREFERENCES)))
                 if p.casefold() in names), None)
    if name is None:
        return []
    command = [ffmpeg.ffmpeg_path(), "-v", "error", "-ss", str(start_s),
               "-i", str(audio_path_or_wav), "-t", str(duration), "-vn",
               "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise ffmpeg.FFmpegError("Could not decode SFX analysis window", command=command,
                                 stderr=result.stderr.decode("utf-8", errors="replace"))
    samples = np.frombuffer(result.stdout, dtype="<f4")
    count = len(samples) // 800
    if count < 31:
        return []
    frames = samples[:count * 800].reshape(count, 800).astype(np.float64)
    db = 10 * np.log10(np.maximum(np.mean(frames * frames, axis=1), 1e-12))
    rise = np.zeros(count)
    for i in range(30, count):
        rise[i] = db[i] - np.median(db[i - 30:i])
    candidates = []
    for i in range(30, count):
        if rise[i] < 6:
            continue
        onset = i
        while onset > 30 and rise[onset - 1] >= 6:
            onset -= 1
        at = onset * .05
        if lo <= at <= hi:
            candidates.append((rise[i], onset))
    if not candidates:
        return []
    _, onset = max(candidates, key=lambda pair: (pair[0], -pair[1]))
    return [{"name": name, "at_s": round(onset * .05, 4),
             "gain_db": sfx.DEFAULT_GAIN_DB, "kind": "impact"}]
