"""Evaluate hype-detection settings against viewer-made Twitch clips, slice by slice.

Chat-only: needs the chat slices downloaded with ``scripts/hype_fetch_chat.py`` and the
viewer-clip list of the VOD (fetched once through ``hype_eval.fetch_viewer_clips`` using
the Twitch app credentials from the environment, then cached as plain JSON without any
credentials). The viewer-clip signal is never fed to the detector: clips are ground truth only.

Usage: python scripts/hype_calibrate.py VOD_ID [--slices 0-3,3-6,...] [--set key=value ...]
"""

from __future__ import annotations

import argparse
import json
import sys

from autoclip import paths
from autoclip.pipeline import hype
from autoclip.stream import hype_eval
from autoclip.stream.chat import ChatLog

CACHE = paths.root() / "hype_cal"


def load_clips(vod: str) -> list[hype_eval.ViewerClip]:
    path = CACHE / f"clips_{vod}.json"
    if path.exists():
        return [hype_eval.ViewerClip(**c) for c in json.loads(path.read_text("utf-8"))]
    clips = hype_eval.fetch_viewer_clips(vod)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([c.__dict__ for c in clips], ensure_ascii=False), encoding="utf-8")
    return clips


def load_slice(vod: str, a_h: float, b_h: float) -> tuple[ChatLog, float, float]:
    s, e = int(a_h * 3600), int(b_h * 3600)
    chat = ChatLog.load(paths.root() / "streams" / f"{vod}_{s}-{e}" / "chat.json")
    chat.duration_s = float(e - s)
    return chat, float(s), float(e - s)


def evaluate(
    chat: ChatLog, offset: float, dur: float, clips, cfg: hype.HypeConfig, *, min_views: int = 0
) -> dict:
    peaks = hype.compute_hype(chat, duration_s=dur, config=cfg)
    windows = [(p.window_start, p.window_end) for p in peaks]
    pool = [c for c in clips if c.views >= min_views]
    out = {"windows": len(peaks)}
    for name, overlap in (("strict", False), ("overlap", True)):
        rate, details = hype_eval.hit_rate(
            pool, windows, top_clips=10, tolerance_s=30, offset_s=offset, max_s=dur, overlap=overlap
        )
        out[name] = (rate, len(details))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("vod")
    ap.add_argument("--slices", default="0-3,3-6,6-9,9-12,12-15,15-18")
    ap.add_argument("--set", nargs="*", default=[], help="HypeConfig overrides key=value")
    ap.add_argument("--floor", type=int, default=0)
    args = ap.parse_args()
    cfg_kwargs = {}
    for item in args.set:
        k, v = item.split("=")
        cfg_kwargs[k] = type(getattr(hype.HypeConfig, k))(v)
    cfg = hype.HypeConfig(**cfg_kwargs)
    clips = load_clips(args.vod)
    for sl in args.slices.split(","):
        a, b = (float(x) for x in sl.split("-"))
        chat, off, dur = load_slice(args.vod, a, b)
        r = evaluate(chat, off, dur, clips, cfg, min_views=args.floor)
        strict, overlap = r["strict"], r["overlap"]
        print(
            f"{sl} {r['windows']} windows: strict {strict[0]:.0%} (n={strict[1]}), "
            f"overlap {overlap[0]:.0%} (n={overlap[1]})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
