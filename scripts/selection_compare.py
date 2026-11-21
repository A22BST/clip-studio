"""Compare clip SELECTION across the free model chain and the current Claude `/clip` run.

Ground truth is the one `stream/hype_eval.py` uses: the most-viewed viewer clips of the same VOD.
For every target (each model of each configured chain bucket that has a key, plus optionally
Claude) the script runs selection on a private copy of one prepared job, maps every picked clip
to VOD time, and prints:

  recall     share of the top-N viewer clips touched by a pick (+/- tolerance)
  precision  share of picks that touch one of the top-N viewer clips
  picks      number of clips chosen, plus valid/invalid and seconds taken

Prepare a job first (`clip stream ... --prepare-only`), so ``candidates.json`` exists. Then:

    python scripts/selection_compare.py JOB_ID VOD_ID --offset-s 0 --dry-run
    python scripts/selection_compare.py JOB_ID VOD_ID --offset-s 0 [--claude] [--only groq,zai]

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


def score(spans, clips, *, offset_s: float, top: int, tol: float) -> tuple[float, float]:
    recall, _ = hype_eval.hit_rate(clips, spans, top_clips=top, tolerance_s=tol,
                                   offset_s=offset_s, overlap=True)
    truth = sorted(clips, key=lambda c: c.views, reverse=True)
    truth = [c for c in truth if c.offset_s - offset_s >= 0][:top]
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


def run_target(job: str, label: str, auto_cfg, restrict, idx: int) -> tuple[Path, float, str]:
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
        select.run_selection(new_id, auto_cfg)
    except Exception as exc:  # report and continue with the next target
        error = f"{type(exc).__name__}: {str(exc)[:120]}"
    finally:
        select.build_chain = original
    return work, time.time() - started, error


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("job")
    ap.add_argument("vod")
    ap.add_argument("--offset-s", type=float, default=0.0, help="VOD time of the job's t=0")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--tolerance", type=float, default=30.0)
    ap.add_argument("--clips-json", type=Path)
    ap.add_argument("--only", default="", help="comma list of chain bucket names")
    ap.add_argument("--claude", action="store_true", help="also run the current Claude selection")
    ap.add_argument("--dry-run", action="store_true", help="list targets and key status only")
    args = ap.parse_args()

    settings = app_config.load()
    only = {s for s in args.only.split(",") if s}
    prov, rows = targets(settings, only, args.claude)
    if args.dry_run:
        for name, model, _e, has_key in rows:
            print(f"{name:24} {model:44} {'key present' if has_key else 'NO KEY (skipped)'}")
        return
    clips = load_viewer_clips(args.vod, args.clips_json)
    base = load_config()
    result_rows = []
    for idx, (name, model, entry, has_key) in enumerate(rows, start=1):
        if not has_key:
            result_rows.append((name, model, "skipped: no key", "", "", "", ""))
            continue
        if entry is None:
            cfg = base.model_copy(update={"selection": base.selection.model_copy(
                update={"backend": "claude"})})
            restrict = None
        else:
            cfg = base.model_copy(update={"selection": base.selection.model_copy(
                update={"backend": "chain"})})
            restrict = chain_mod.ChainProvider(settings)
            restrict.entries = [entry.model_copy(update={"models": [model], "model": model})]
        work, secs, error = run_target(args.job, name, cfg, restrict, idx)
        if error:
            result_rows.append((name, model, error, "", "", "", f"{secs:.0f}s"))
            continue
        spans = pick_spans(work)
        recall, precision = score(spans, clips, offset_s=args.offset_s, top=args.top,
                                  tol=args.tolerance)
        result_rows.append((name, model, "ok", str(len(spans)), f"{recall:.0%}",
                            f"{precision:.0%}", f"{secs:.0f}s"))
    print(f"\njob {args.job}  vod {args.vod}  top {args.top} viewer clips  "
          f"tolerance {args.tolerance:.0f}s  (one job = small sample)")
    print(f"{'bucket':22}{'model':44}{'status':28}{'picks':>6}{'recall':>8}{'prec.':>7}{'time':>7}")
    for r in result_rows:
        print(f"{r[0]:22}{r[1]:44}{r[2][:27]:28}{r[3]:>6}{r[4]:>8}{r[5]:>7}{r[6]:>7}")


if __name__ == "__main__":
    main()
