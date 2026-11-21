"""Compare clip SELECTION across the free model chain and the current Claude `/clip` run.

Ground truth is the one `stream/hype_eval.py` uses: the most-viewed viewer clips of the same VOD.
For every target (each model of each configured chain bucket that has a key, plus optionally
Claude) the script runs selection on a private copy of one prepared job, maps every picked clip
to VOD time, and prints:

  recall     share of the top-N viewer clips touched by a pick (+/- tolerance)
  precision  share of picks that touch one of the top-N viewer clips
  CEILING    recall achievable by covering every candidate window
  ranks      candidate ranks selected by each target
  picks      number of clips chosen, plus valid/invalid and seconds taken

Prepare a job first (`clip stream ... --prepare-only`), so ``candidates.json`` exists. Then:

    python scripts/selection_compare.py JOB_ID VOD_ID --offset-s 0 --dry-run
    python scripts/selection_compare.py JOB_ID VOD_ID --offset-s 0 [--claude] [--only groq,zai]
    python scripts/selection_compare.py --jobs JOB1:VOD1:0:clips1.json JOB2:VOD2:3600:clips2.json

JOB_ID's ``candidates.json`` is only copied, never changed. Viewer clips come from the Twitch API
(TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET) or from ``--clips-json`` (a cache written by
``hype_fusion_run.py``). Free models need keys in the keyring (``autoclip config set-secret``);
targets without a key are listed and skipped. A single job is a small sample: run several jobs
before drawing conclusions. Nothing here posts or renders anything.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from autoclip import config as app_config
from autoclip import paths
from autoclip.auto import select
from autoclip.auto.config import load_config
from autoclip.providers import chain as chain_mod
from autoclip.stream import hype_eval
from autoclip.stream.pipeline import load_highlights


def load_viewer_clips(vod: str, clips_json: Path | None) -> list[hype_eval.ViewerClip]:
    if clips_json:
        raw = json.loads(clips_json.read_text(encoding="utf-8"))
        return [hype_eval.ViewerClip(**c) for c in raw]
    return hype_eval.fetch_viewer_clips(vod)


def pick_spans(work: Path) -> list[tuple[float, float]]:
    """Map each picked clip's word range to seconds (linear inside its candidate window)."""
    cand = json.loads((work / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    spans = []
    for clip, _meta in load_highlights(work / "highlights.json"):
        for c in cand:
            lo, hi = c["first_word"], c["last_word"]
            if lo <= clip.start_word_index and clip.end_word_index <= hi:
                frac = (hi - lo) or 1
                a, b = c["window_start_s"], c["window_end_s"]
                spans.append(
                    (
                        a + (b - a) * (clip.start_word_index - lo) / frac,
                        a + (b - a) * (clip.end_word_index - lo) / frac,
                    )
                )
                break
    return spans


def score(spans, clips, *, offset_s: float, top: int, tol: float,
          max_s: float | None = None) -> tuple[float, float]:
    """Recall and precision against the top viewer clips INSIDE the job's time range."""
    recall, _ = hype_eval.hit_rate(clips, spans, top_clips=top, tolerance_s=tol,
                                   offset_s=offset_s, max_s=max_s, overlap=True)
    truth = sorted(clips, key=lambda c: c.views, reverse=True)
    end_s = max_s if max_s is not None else float("inf")
    inside = [c for c in truth if 0 <= c.offset_s - offset_s <= end_s]
    truth = inside[:top]
    spans_vod = [(a + offset_s, b + offset_s) for a, b in spans]
    hits = sum(
        any(c.offset_s <= b + tol and c.offset_s + c.duration_s >= a - tol for c in truth)
        for a, b in spans_vod
    )
    return recall, (hits / len(spans) if spans else 0.0)


def targets(settings, only: set[str], include_claude: bool):
    prov = chain_mod.ChainProvider(settings)
    rows = []
    for entry in prov.entries:
        if only and entry.name not in only:
            continue
        local = entry.name.lower() == "ollama"
        has_key = local or bool(app_config.get_secret(entry.key_name, settings))
        for model in entry.models:
            rows.append((entry.name, model, entry, has_key))
    if include_claude:
        rows.append(("claude-cli", "sonnet", None, True))
    return prov, rows


def run_target(
    job: str, label: str, auto_cfg, restrict, idx: int, retries: int = 3
) -> tuple[Path, float, str]:
    new_id = f"{job}-cmp{idx}"
    work = paths.job_work_dir(new_id)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(paths.job_work_dir(job) / "candidates.json", work / "candidates.json")
    original = select.build_chain
    if restrict is not None:
        select.build_chain = lambda: restrict
    started = time.time()
    error = ""
    try:
        for attempt in range(1, retries + 1):
            chain_mod._COOLDOWNS.clear()  # a cooldown from the previous target must not leak
            try:
                select.run_selection(new_id, auto_cfg)
                error = ""
                break
            except Exception as exc:  # report and continue with the next target
                error = f"{type(exc).__name__}: {exc}"
                if "No usable chain entries" not in error or attempt == retries:
                    break
                time.sleep(20)  # transient overload (429/503): wait and try again
    finally:
        select.build_chain = original
    return work, time.time() - started, error


def parse_job_spec(spec: str) -> tuple[str, str, float, Path | None]:
    """Split only three colons so Windows cache paths retain their drive letter."""
    parts = spec.split(":", 3)
    if len(parts) < 3 or not parts[0] or not parts[1]:
        raise argparse.ArgumentTypeError("Expected JOB:VOD:OFFSET[:CLIPS_JSON]")
    try:
        offset = float(parts[2])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Job OFFSET must be a number") from exc
    return parts[0], parts[1], offset, Path(parts[3]) if len(parts) == 4 else None


def candidate_ceiling(data, clips, *, offset_s, top, tol, max_s=None):
    """Best recall reachable by covering all candidate windows."""
    spans = [(c["window_start_s"], c["window_end_s"]) for c in data["candidates"]]
    return score(spans, clips, offset_s=offset_s, top=top, tol=tol, max_s=max_s)[0]


def picked_ranks(work: Path) -> list[int]:
    """One-based candidate pool ranks, in pick order (including repeated ranks)."""
    candidates = json.loads((work / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    ranks = []
    for clip, _meta in load_highlights(work / "highlights.json"):
        for rank, candidate in enumerate(candidates, start=1):
            if (candidate["first_word"] <= clip.start_word_index
                    and clip.end_word_index <= candidate["last_word"]):
                ranks.append(candidate.get("rank", rank))
                break
    return ranks


def argument_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("job", nargs="?")
    ap.add_argument("vod", nargs="?")
    ap.add_argument("--jobs", nargs="+", type=parse_job_spec,
                    help="JOB:VOD:OFFSET[:CLIPS_JSON] specs")
    ap.add_argument("--offset-s", type=float, default=0.0, help="VOD time of the job's t=0")
    ap.add_argument("--max-s", type=float, default=None,
                    help="job length in seconds (default: stream duration in candidates.json)")
    ap.add_argument("--retries", type=int, default=3,
                    help="tries per target on transient 429/503 (each uses daily budget)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--tolerance", type=float, default=30.0)
    ap.add_argument("--clips-json", type=Path)
    ap.add_argument("--only", default="", help="comma list of chain bucket names")
    ap.add_argument("--claude", action="store_true", help="also run the current Claude selection")
    ap.add_argument("--dry-run", action="store_true", help="list targets and key status only")
    return ap


def main() -> None:
    ap = argument_parser()
    args = ap.parse_args()
    if args.jobs:
        if args.job or args.vod:
            ap.error("Use positional JOB VOD or --jobs, not both")
        jobs = args.jobs
    elif args.job and args.vod:
        jobs = [(args.job, args.vod, args.offset_s, args.clips_json)]
    else:
        ap.error("Supply JOB VOD or --jobs JOB:VOD:OFFSET[:CLIPS_JSON]")
    import logging
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s",
                        filename=f"selection_compare_{jobs[0][0]}.log", encoding="utf-8")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = app_config.load()
    only = {s for s in args.only.split(",") if s}
    _prov, rows = targets(settings, only, args.claude)
    if args.dry_run:
        for name, model, _e, has_key in rows:
            print(f"{name:24} {model:44} {'key present' if has_key else 'NO KEY (skipped)'}")
        return
    base = load_config()
    means = {(name, model): [] for name, model, _entry, _key in rows}
    for job, vod, offset_s, clips_json in jobs:
        clips = load_viewer_clips(vod, clips_json or args.clips_json)
        data = json.loads((paths.job_work_dir(job) / "candidates.json").read_text(encoding="utf-8"))
        max_s = args.max_s
        if max_s is None:
            max_s = float(data.get("stream", {}).get("duration_s") or 0) or None
        ceiling = candidate_ceiling(data, clips, offset_s=offset_s, top=args.top,
                                    tol=args.tolerance, max_s=max_s)
        print(f"\njob {job}  vod {vod}  top {args.top} viewer clips  "
              f"tolerance {args.tolerance:.0f}s  CEILING {ceiling:.0%}")
        print(f"{'bucket':22}{'model':44}{'picks':>6}{'recall':>8}{'prec.':>7}"
              f"{'time':>7}  ranks  status")
        for idx, (name, model, entry, has_key) in enumerate(rows, start=1):
            if not has_key:
                print(f"{name:22}{model:44} skipped:no_key")
                continue
            cfg = base.model_copy(update={"selection": base.selection.model_copy(
                update={"backend": "claude" if entry is None else "chain"})})
            restrict = None
            if entry is not None:
                restrict = chain_mod.ChainProvider(settings)
                restrict.entries = [entry.model_copy(update={"models": [model], "model": model})]
            work, secs, error = run_target(job, name, cfg, restrict, idx, args.retries)
            if error:
                print(f"{name:22}{model:44}{'':>21}{secs:6.0f}s  []  {error}")
                print(f"ERROR {name} {model}: {error}")
                continue
            spans = pick_spans(work)
            recall, precision = score(spans, clips, offset_s=offset_s, top=args.top,
                                      tol=args.tolerance, max_s=max_s)
            means[(name, model)].append((recall, precision, ceiling))
            print(f"{name:22}{model:44}{len(spans):6}{recall:8.0%}{precision:7.0%}"
                  f"{secs:6.0f}s  {picked_ranks(work)}  ok")
    if len(jobs) > 1:
        print("\nMEAN per target (successful jobs only; n/total shown)")
        for (name, model), values in means.items():
            if values:
                recall, precision, ceiling = (sum(v[i] for v in values) / len(values)
                                               for i in range(3))
                print(f"{name:22}{model:44} n={len(values)}/{len(jobs)} "
                      f"recall {recall:.0%} precision {precision:.0%} CEILING {ceiling:.0%}")
            else:
                print(f"{name:22}{model:44} n=0/{len(jobs)} unavailable")


if __name__ == "__main__":
    main()
