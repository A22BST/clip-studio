"""Run the pre-registered fusion experiment (docs/hype-fusion-protocol.md), slice by slice.

    python scripts/hype_fusion_run.py slices VOD            # per-slice clip totals only (selection)
    python scripts/hype_fusion_run.py prep VOD START_H END_H   # chat + audio + transcript (slow)
    python scripts/hype_fusion_run.py candidates VOD START_H END_H   # detectors -> pool -> view
    python scripts/hype_fusion_run.py score VOD START_H END_H ...    # ONLY after rankings exist

Nothing here feeds viewer clips to a detector or to the ranker: clips are read only by ``slices``
(aggregate view totals per slice) and ``score`` (after ``ranking.json`` was written).
Work folder per slice: ``<root>/fusion/<vod>_<start>-<end>/``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from autoclip import paths
from autoclip.pipeline import audio_hype, ffmpeg, hype, prepare, transcript_hype
from autoclip.pipeline.transcript import Transcript
from autoclip.stream import fusion, hype_eval, ingest
from autoclip.stream.chat import ChatLog

POOL_N = 20  # peaks per source that enter the pool
ARM_N = 15  # windows per arm per 3 h slice
ROOT = paths.root() / "fusion"


def slice_dir(vod: str, a_h: float, b_h: float) -> Path:
    return ROOT / f"{vod}_{int(a_h * 3600)}-{int(b_h * 3600)}"


def load_clips(vod: str) -> list[hype_eval.ViewerClip]:
    cache = ROOT / f"clips_{vod}.json"
    if cache.exists():
        return [hype_eval.ViewerClip(**c) for c in json.loads(cache.read_text("utf-8"))]
    clips = hype_eval.fetch_viewer_clips(vod)  # credentials come from the environment only
    ROOT.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([asdict(c) for c in clips]), encoding="utf-8")
    return clips


def cmd_slices(args: argparse.Namespace) -> None:
    """Selection aid: only aggregate numbers per aligned 3 h block, never individual offsets."""
    clips = load_clips(args.vod)
    print(f"{len(clips)} viewer clips with a VOD offset in total")
    for a in range(0, int(args.total_h), 3):
        b = min(a + 3, args.total_h)
        sel = fusion.select_truth(clips, offset_s=a * 3600, duration_s=(b - a) * 3600)
        floor = fusion.select_truth(
            clips, offset_s=a * 3600, duration_s=(b - a) * 3600, min_views=50
        )
        print(
            f"{a}-{b} h: top-10 views sum {sum(c.views for c in sel)}, "
            f"clips>=50 views: {len(floor)}"
        )


def cmd_prep(args: argparse.Namespace) -> None:
    from autoclip.config import WhisperSettings
    from autoclip.pipeline import transcribe

    a, b = int(args.start_h * 3600), int(args.end_h * 3600)
    out = slice_dir(args.vod, args.start_h, args.end_h)
    out.mkdir(parents=True, exist_ok=True)
    src = ingest.ingest_twitch_vod(
        f"https://www.twitch.tv/videos/{args.vod}", start=a, end=b, skip_video=True
    )
    chat = ChatLog.load(src.chat_path)
    chat.duration_s = float(b - a)
    chat.save(out / "chat.json")
    wav = out / "audio.wav"
    if not wav.exists():
        audio_only = out / "audio_only.mp4"
        if not audio_only.exists():
            cmd = [
                ingest.find_cli(),
                "videodownload",
                "--id",
                args.vod,
                "-o",
                str(audio_only),
                "--quality",
                "Audio",
                "--beginning",
                f"{a}s",
                "--ending",
                f"{b}s",
                "--ffmpeg-path",
                ffmpeg.ffmpeg_path(),
                "--collision",
                "Overwrite",
                "--banner",
                "false",
            ]
            subprocess.run(cmd, check=True)
        prepare.extract_audio(audio_only, wav)
        audio_only.unlink(missing_ok=True)
    tpath = out / "transcript.json"
    if not tpath.exists():
        settings = WhisperSettings(model="large-v3-turbo")
        tr = transcribe.transcribe(wav, settings, duration_s=float(b - a))
        tr.save(tpath)
    print("prepared", out)


def adopt(args: argparse.Namespace) -> None:
    """Re-use an already prepared slice (audio + transcript + chat) from an earlier job."""
    out = slice_dir(args.vod, args.start_h, args.end_h)
    out.mkdir(parents=True, exist_ok=True)
    for name, src in (
        ("audio.wav", Path(args.audio)),
        ("transcript.json", Path(args.transcript)),
        ("chat.json", Path(args.chat)),
    ):
        target = out / name
        if not target.exists():
            target.write_bytes(src.read_bytes())
    print("adopted", out)


def _peak_dict(p) -> dict:
    return {
        "t": p.t,
        "score": p.score,
        "window_start": p.window_start,
        "window_end": p.window_end,
        "reasons": p.reasons,
        "sample_messages": list(getattr(p, "sample_messages", []) or []),
    }


class _P:
    def __init__(self, d: dict) -> None:
        self.__dict__.update(d)


def cmd_candidates(args: argparse.Namespace) -> None:
    out = slice_dir(args.vod, args.start_h, args.end_h)
    dur = (args.end_h - args.start_h) * 3600.0
    chat = ChatLog.load(out / "chat.json")
    chat.duration_s = dur
    transcript = Transcript.load(out / "transcript.json")
    peaks = {
        "chat": hype.compute_hype(chat, duration_s=dur, config=hype.HypeConfig(top_n=POOL_N)),
        "audio": audio_hype.compute_audio_hype(out / "audio.wav", duration_s=dur, top_n=POOL_N),
        "transcript": transcript_hype.compute_transcript_hype(
            transcript, duration_s=dur, top_n=POOL_N
        ),
    }
    (out / "peaks.json").write_text(
        json.dumps({k: [_peak_dict(p) for p in v] for k, v in peaks.items()}, indent=1),
        encoding="utf-8",
    )
    cands = fusion.pool_candidates(peaks)
    messages = sorted(chat.messages, key=lambda m: m.t)
    lines = [
        f"# Ranking view {out.name}: {len(cands)} candidates (slice time, h:mm:ss)\n",
        "Pick 15 candidate ids. Signals: rank within its own source (1 = best of 20) and score.\n",
    ]
    for c in cands:
        sig = "; ".join(
            f"{n} #{r} ({s:.1f}: {', '.join(c.reasons.get(n, [])[:3])})"
            for n, (r, s) in sorted(c.signals.items())
        )
        sample = (
            c.chat_sample
            or [f"{m.user}: {m.text}" for m in messages if c.start <= m.t <= c.end][:6]
        )
        text = fusion.window_text(transcript, c.start, c.end)
        lines.append(
            f"## id {c.id}  {_hms(c.start)}-{_hms(c.end)} ({c.length:.0f}s)\n"
            f"signals: {sig}\n"
            f"chat: {' | '.join(sample[:6]) or '(none)'}\n"
            f"transcript: {text or '(no speech)'}\n"
        )
    (out / "ranking_view.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "candidates.json").write_text(
        json.dumps([{**asdict(c), "rrf": c.rrf} for c in cands], indent=1), encoding="utf-8"
    )
    print(out.name, {k: len(v) for k, v in peaks.items()}, "pooled", len(cands))


def _hms(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def cmd_score(args: argparse.Namespace) -> None:
    clips = load_clips(args.vod)
    rows = []
    for a_h, b_h in args.slice_pairs:
        out = slice_dir(args.vod, a_h, b_h)
        ranking_file = out / "ranking.json"
        if not ranking_file.exists():
            sys.exit(f"{ranking_file} missing: rank BEFORE scoring")
        dur = (b_h - a_h) * 3600.0
        offset = a_h * 3600.0
        peaks = {
            k: [_P(d) for d in v]
            for k, v in json.loads((out / "peaks.json").read_text("utf-8")).items()
        }
        cands = {c["id"]: c for c in json.loads((out / "candidates.json").read_text("utf-8"))}
        chosen = json.loads(ranking_file.read_text("utf-8"))["ids"][:ARM_N]
        rrf = sorted(cands.values(), key=lambda c: (-c["rrf"], c["t"]))[:ARM_N]
        arms = {
            name: [(p.window_start, p.window_end) for p in peaks[name][:ARM_N]]
            for name in ("chat", "audio", "transcript")
        }
        arms["fused_claude"] = [(cands[i]["start"], cands[i]["end"]) for i in chosen]
        arms["fused_rrf"] = [(c["start"], c["end"]) for c in rrf]
        arms["pool_all"] = [(c["start"], c["end"]) for c in cands.values()]
        for variant, floor in (("top10", 0), ("floor50", 50)):
            truth = fusion.select_truth(
                clips, offset_s=offset, duration_s=dur, top_clips=10, min_views=floor
            )
            for name, windows in arms.items():
                row = {
                    "slice": f"{a_h:g}-{b_h:g}",
                    "variant": variant,
                    "n_clips": len(truth),
                    "arm": name,
                    "windows": len(windows),
                    "coverage": fusion.coverage(windows, dur),
                }
                for mode, overlap in (("strict", False), ("overlap", True)):
                    h = fusion.hits(truth, windows, overlap=overlap)
                    row[mode] = h / len(truth) if truth else 0.0
                    row[f"{mode}_hits"] = h
                    if name != "pool_all":
                        mean, p95 = fusion.random_baseline(
                            truth, [e - s for s, e in windows], dur, overlap=overlap
                        )
                        row[f"{mode}_rand_mean"], row[f"{mode}_rand_p95"] = mean, p95
                rows.append(row)
    (ROOT / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(json.dumps(rows, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("slices")
    s.add_argument("vod")
    s.add_argument("--total-h", type=float, default=11.6)
    for name in ("prep", "candidates"):
        s = sub.add_parser(name)
        s.add_argument("vod")
        s.add_argument("start_h", type=float)
        s.add_argument("end_h", type=float)
    s = sub.add_parser("adopt")
    s.add_argument("vod")
    s.add_argument("start_h", type=float)
    s.add_argument("end_h", type=float)
    s.add_argument("--audio", required=True)
    s.add_argument("--transcript", required=True)
    s.add_argument("--chat", required=True)
    s = sub.add_parser("score")
    s.add_argument("vod")
    s.add_argument("slices", nargs="+", help="e.g. 2-5 0-3")
    args = ap.parse_args()
    if args.cmd == "score":
        args.slice_pairs = [tuple(float(x) for x in s.split("-")) for s in args.slices]
    {
        "slices": cmd_slices,
        "prep": cmd_prep,
        "adopt": adopt,
        "candidates": cmd_candidates,
        "score": cmd_score,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
