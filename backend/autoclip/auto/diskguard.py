"""Skip expensive work when the AutoClip volume is short of space."""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import paths
from .config import AutoConfig


def free_gb(path: Path | str) -> float:
    """Free GiB on the volume containing path, even before path exists."""
    target = Path(path).resolve()
    while not target.exists() and target != target.parent:
        target = target.parent
    return shutil.disk_usage(target).free / 1024**3


def disk_ok(config: AutoConfig) -> tuple[bool, str]:
    try:
        available = free_gb(paths.root())
    except OSError:
        return False, "Cannot check free disk space; heavy work skipped"
    minimum = config.disk.min_free_gb
    if available < minimum:
        return False, f"Low disk space: {available:.1f} GiB free; {minimum:g} GiB required"
    return True, ""
