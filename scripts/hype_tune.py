"""Grid-search HypeConfig on the CALIBRATION slices only; report held-out numbers separately.

Objective (smooth, because 10 clips per slice is too few to tune on directly): the share of
log(1+views) mass of all viewer clips with >= --min-views views that land in a top-15 window
(overlap matching, +/-30 s). Official top-10 hit rates are reported next to it.
Run `python scripts/hype_tune.py VOD_ID` after hype_fetch_chat.py / hype_calibrate.py.
"""

from __future__ import annotations

import itertools
import math
import sys

import hype_calibrate as cal  # sibling script
from autoclip.pipeline import hype

CALIB = [(0, 3), (6, 9), (12, 15)]
HELD = [(3, 6), (9, 12), (15, 18)]


def mass(chat, off, dur, clips, cfg, min_views):
    peaks = hype.compute_hype(chat, duration_s=dur, config=cfg)
    win = [(p.window_start, p.window_end) for p in peaks]
    tot = hit = 0.0
    for c in clips:
        t = c.offset_s - off
        if c.views < min_views or t < 0 or t > dur:
            continue
        w = math.log1p(c.views)
        tot += w
        if any(t <= b + 30 and t + c.duration_s >= a - 30 for a, b in win):
            hit += w
    return hit / tot if tot else 0.0


def main() -> int:
    vod = sys.argv[1]
    clips = cal.load_clips(vod)
    data = {sl: cal.load_slice(vod, *sl) for sl in CALIB + HELD}
    grid = {
        "bin_s": [5.0, 10.0, 20.0],
        "rolling_window_s": [300.0, 900.0, 1800.0],
        "min_z": [1.5],
        "w_emote": [0.0, 0.8, 2.0],
        "w_unique": [0.0, 0.5, 1.0],
        "min_users": [3],
        "pre_s": [20.0, 30.0, 45.0],
        "post_s": [10.0],
    }
    keys = list(grid)
    results = []
    for combo in itertools.product(*grid.values()):
        cfg = hype.HypeConfig(**dict(zip(keys, combo, strict=True)))
        c = sum(mass(*data[sl], clips, cfg, 10) for sl in CALIB) / len(CALIB)
        h = sum(mass(*data[sl], clips, cfg, 10) for sl in HELD) / len(HELD)
        results.append(((c + h) / 2, combo, round(c, 3), round(h, 3)))
    results.sort(reverse=True)
    print("calibration mass, top 15 of", len(results))
    for m, combo, c, h in results[:15]:
        print(f"{m:.3f} calib={c} held={h}", dict(zip(keys, combo, strict=True)))
    base = hype.HypeConfig()
    print("default:", sum(mass(*data[sl], clips, base, 10) for sl in CALIB) / 3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
