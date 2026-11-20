"""Chat previews: a small copy of a clip that fits the chat service's upload limit.

The preview is only for looking at. Approval and posting always use the full-quality file (its
SHA-256 is what the approval is tied to), so a re-encode never changes what gets posted.
Previews are cached in ``<root>/auto/previews/`` keyed by the original's hash and the profile.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..pipeline.ffmpeg import ffmpeg_path
from .config import auto_dir

#: (height px, video kbps) tried in order until the file fits. Audio is AAC 96k.
LADDERS: dict[str, list[tuple[int, int]]] = {
    "telegram": [(720, 2500), (720, 1500), (540, 900)],  # Bot API upload limit 50 MB
    "discord": [(540, 1000), (540, 700), (480, 450), (360, 300)],  # 10 MB without boost
}


class PreviewError(RuntimeError):
    pass


def encode(original: Path, target: Path, height: int, video_kbps: int) -> None:
    cmd = [
        ffmpeg_path(), "-y", "-i", str(original), "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-preset", "fast",
        "-b:v", f"{video_kbps}k", "-maxrate", f"{int(video_kbps * 1.2)}k",
        "-bufsize", f"{video_kbps * 2}k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(target),
    ]  # fmt: skip
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise PreviewError(f"ffmpeg failed: {(done.stderr or '')[-300:]}")


def make_preview(
    original: Path,
    sha: str,
    *,
    profile: str,
    limit_bytes: int,
    out_dir: Path | None = None,
    encoder=encode,
) -> Path:
    """The file to show in chat: the original when it already fits, else a cached copy."""
    original = Path(original)
    if original.stat().st_size <= limit_bytes:
        return original  # already small enough: show the real thing
    directory = out_dir or auto_dir() / "previews"
    directory.mkdir(parents=True, exist_ok=True)
    last = ""
    for height, kbps in LADDERS[profile]:
        target = directory / f"{sha[:16]}-{profile}-{height}p-{kbps}k.mp4"
        if not target.is_file():
            encoder(original, target, height, kbps)
        if target.stat().st_size <= limit_bytes:
            return target
        last = f"{target.stat().st_size} bytes at {height}p/{kbps}k"
    raise PreviewError(f"could not get the preview under {limit_bytes} bytes ({last})")
