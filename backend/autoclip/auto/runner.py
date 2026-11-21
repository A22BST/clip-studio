"""Job state machine: one queued VOD slice -> clips waiting for approval.

    queued -> running: prepare (clip stream --prepare-only)   [download, transcribe, hype]
                       select  (claude -p /clip)              [3b]
                       render  (clip stream --highlights)     [layouts, captions, rules, QA]
                       ingest  (report.json -> clips table, status pending_approval)
           -> done | failed | queued (retry)

Session 1's code is used only through its CLI and its report/highlights files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import paths
from .config import AutoConfig
from .select import SelectionError, run_selection
from .store import Store

JOB_ID_RE = re.compile(r"Job id:\s*([0-9a-f]+)")
MAX_ATTEMPTS = 2


class JobError(RuntimeError):
    pass


def _time_arg(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def stream_command(job: dict[str, Any], extra: list[str]) -> list[str]:
    cmd = [sys.executable, "-m", "autoclip.stream.cli", "stream"]
    cmd.append(job["url"] or job["vod_id"])
    cmd += ["--campaign", job["campaign_key"]]
    if job["start_s"] or job["end_s"]:
        cmd += ["--start", _time_arg(job["start_s"])]
        if job["end_s"]:
            cmd += ["--end", _time_arg(job["end_s"])]
    return cmd + extra


def _run(cmd: list[str], runner: Callable[..., Any], timeout_s: int) -> subprocess.CompletedProcess:
    done = runner(
        cmd, capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
        check=False, env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        encoding="utf-8", errors="replace",
    )  # fmt: skip
    return done


def source_folder(job: dict[str, Any]) -> Path:
    """Where session 1's ingest keeps this slice (mirrors ingest.ingest_twitch_vod naming)."""
    start, end = int(job["start_s"] or 0), int(job["end_s"] or 0)
    suffix = f"_{start}-{end}" if (start or end) else ""
    return paths.root() / "streams" / f"{job['vod_id']}{suffix}"


def process_job(
    store: Store,
    config: AutoConfig,
    job: dict[str, Any],
    *,
    runner: Callable[..., Any] = subprocess.run,
    select: Callable[..., Path] = run_selection,
) -> int:
    """Run one claimed job end to end. Returns the number of clips queued for approval."""
    job_id = job["id"]
    try:
        autoclip_job = job["autoclip_job_id"]
        work = paths.job_work_dir(autoclip_job) if autoclip_job else None
        if not (work and (work / "candidates.json").is_file()):
            done = _run(stream_command(job, ["--prepare-only"]), runner, 6 * 3600)
            match = JOB_ID_RE.search(done.stdout or "")
            if done.returncode != 0 or not match:
                tail = ((done.stderr or "") + (done.stdout or ""))[-400:]
                raise JobError(f"prepare failed (exit {done.returncode}): {tail}")
            autoclip_job = match.group(1)
            store.update_job(job_id, autoclip_job_id=autoclip_job)
        highlights = select(autoclip_job, config)
        done = _run(stream_command(job, ["--highlights", str(highlights)]), runner, 3 * 3600)
        export_dir = paths.exports_dir() / autoclip_job
        if done.returncode != 0 or not (export_dir / "report.json").is_file():
            tail = ((done.stderr or "") + (done.stdout or ""))[-400:]
            raise JobError(f"render failed (exit {done.returncode}): {tail}")
        store.update_job(job_id, export_dir=str(export_dir))
        added = ingest_report(store, job, autoclip_job, export_dir)
        store.update_job(job_id, state="done", last_error="")
        store.log_event("job_done", f"job {job_id}: {added} clips for approval")
        return added
    except (JobError, SelectionError, subprocess.TimeoutExpired, OSError) as exc:
        message = f"{type(exc).__name__}: {exc}"[:800]
        retry = job["attempts"] < MAX_ATTEMPTS
        store.update_job(job_id, state="queued" if retry else "failed", last_error=message)
        store.log_event(
            "job_error", f"job {job_id} ({'will retry' if retry else 'gave up'}): {message[:300]}"
        )
        return 0


def _find_highlight(autoclip_job: str, title: str) -> dict[str, Any] | None:
    path = paths.job_work_dir(autoclip_job) / "highlights.json"
    try:
        for item in json.loads(path.read_text(encoding="utf-8")).get("clips", []):
            if str(item.get("title", "")).strip() == title.strip():
                return item
    except (OSError, ValueError):
        pass
    return None


def ingest_report(store: Store, job: dict[str, Any], autoclip_job: str, export_dir: Path) -> int:
    """Turn exported entries of report.json into clips awaiting approval (idempotent per path)."""
    from . import gate

    report = json.loads((export_dir / "report.json").read_text(encoding="utf-8"))
    known = {c["path"] for c in store.list_clips(job_id=job["id"])}
    added = 0
    for entry in report:
        if entry.get("status") != "exported" or not entry.get("path"):
            store.log_event(
                "clip_skipped",
                f"job {job['id']} '{entry.get('title', '')[:60]}': {entry.get('status')} "
                + "; ".join(entry.get("violations", []))[:200],
            )
            continue
        path = Path(entry["path"])
        if str(path) in known or not path.is_file():
            continue
        highlight = _find_highlight(autoclip_job, entry["title"]) or {}
        try:
            duration = gate._probe_duration(path)
        except Exception:
            duration = float(entry["end_s"]) - float(entry["start_s"])
        store.add_clip(
            job_id=job["id"],
            campaign_key=job["campaign_key"],
            title=entry["title"],
            hook=entry.get("hook", ""),
            caption=entry.get("caption", ""),
            hashtags=entry.get("hashtags", []),
            mentions=highlight.get("mentions", []),
            qa_score=int(entry.get("qa_score", 0)),
            spoiler_level=entry.get("spoiler_level", "none"),
            layout=entry.get("layout_used", ""),
            path=str(path),
            duration_s=duration,
            report_status="exported",
            highlight=highlight,
            stream_date=job.get("vod_created_at") or "",
            status="pending_approval",
        )
        added += 1
    return added


def cleanup_sources(store: Store, config: AutoConfig) -> int:
    """Delete downloaded VODs of finished jobs once none of their clips awaits a decision."""
    if not config.delete_source_after_render:
        return 0
    freed = 0
    for job in store.list_jobs("done"):
        clips = store.list_clips(job_id=job["id"])
        if any(c["status"] in ("pending_approval", "editing") for c in clips):
            continue
        folder = source_folder(job)
        video = folder / "vod.mp4"
        if video.is_file():
            freed += video.stat().st_size
            video.unlink()
        if job["autoclip_job_id"]:
            for wav in paths.job_work_dir(job["autoclip_job_id"]).glob("*.wav"):
                wav.unlink(missing_ok=True)
        if folder.is_dir() and not any(folder.glob("*.mp4")):
            shutil.rmtree(folder, ignore_errors=True)
    return freed


def rerender_clip(
    store: Store,
    clip: dict[str, Any],
    new_hook: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> Path | None:
    """Edit-hook support: re-render ONE clip with a new hook. Returns the new file or None.

    Needs the VOD still on disk (cleanup_sources waits while a clip is pending) and the stored
    highlight item. The one-clip highlights file keeps the other clips' files untouched.
    """
    job = store.get_job(clip["job_id"])
    item = dict(clip["highlight"] or {})
    if not job or not item or not job["autoclip_job_id"]:
        return None
    item["hook"] = new_hook
    one = paths.job_work_dir(job["autoclip_job_id"]) / f"highlights_edit_{clip['id']}.json"
    one.write_text(json.dumps({"clips": [item]}, ensure_ascii=False), encoding="utf-8")
    done = _run(stream_command(job, ["--highlights", str(one)]), runner, 3600)
    report = paths.exports_dir() / job["autoclip_job_id"] / "report.json"
    if done.returncode != 0 or not report.is_file():
        return None
    for entry in json.loads(report.read_text(encoding="utf-8")):
        if entry.get("status") == "exported" and entry.get("path"):
            return Path(entry["path"])
    return None
