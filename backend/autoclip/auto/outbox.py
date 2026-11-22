"""Local, best-effort handoff of finished clips. Never uploads or renders media."""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths
from .campaign_meta import campaigns_dir
from .config import AutoConfig

log = logging.getLogger(__name__)


def outbox_dir(config: AutoConfig) -> Path:
    return (
        Path(config.outbox.dir).expanduser()
        if config.outbox.dir
        else campaigns_dir().parent / "to-post" / "auto"
    )


def today_count(config: AutoConfig, now: datetime | None = None) -> int:
    ledger = outbox_dir(config) / "outbox.json"
    if not ledger.exists():
        return 0
    day = (now or datetime.now()).date().isoformat()
    entries = json.loads(ledger.read_text(encoding="utf-8"))
    return sum(e["date"] == day and e["status"] == "copied" for e in entries.values())


def _caption(entry: dict[str, Any]) -> str:
    # The report's tag list is authoritative, including when the caption has stale tags.
    caption = re.sub(r"(?<!\w)#[\w]+", "", entry.get("caption", "")).strip()
    tags = " ".join("#" + tag.lstrip("#") for tag in entry.get("hashtags", []))
    return "\n\n".join(part for part in (caption, tags) if part) + "\n"


def _copy(source: Path, folder: Path, caption: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        stem = source.stem + (f"-{number}" if number > 1 else "")
        target = folder / f"{stem}.mp4"
        text = target.with_suffix(".txt")
        if text.exists():
            number += 1
            continue
        try:
            # Exclusive creation also prevents simultaneous ticks overwriting a clip.
            output = target.open("xb")
        except FileExistsError:
            number += 1
            continue
        with output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output)
        with text.open("x", encoding="utf-8") as handle:
            handle.write(caption)
        return target


def _one_line(value: Any) -> str:
    return " ".join(str(value).split())


def export_job(
    export_dir: Path,
    config: AutoConfig,
    *,
    job_id: str = "",
    vod_id: str = "",
    work_dir: Path | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Copy eligible report entries, returning decisions; failures never escape to the tick.

    Dry runs still populate the local outbox, marked in INDEX.md. A missing transcript
    holds otherwise eligible clips for review rather than bypassing the keyword gate.
    """
    results: list[dict[str, Any]] = []
    try:
        export_dir = Path(export_dir)
        job_id = job_id or export_dir.name
        work_dir = work_dir or paths.job_work_dir(job_id)
        report = json.loads((export_dir / "report.json").read_text(encoding="utf-8"))
        markdown_path = export_dir / "report.md"
        markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
        try:
            transcript = json.loads((work_dir / "transcript.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            transcript = None
        root = outbox_dir(config)
        ledger_path = root / "outbox.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
        day = (now or datetime.now()).date().isoformat()
        for entry in report:
            decision = {"clip": entry.get("title", ""), "status": "skipped", "reason": ""}
            results.append(decision)
            try:
                duration = float(entry["end_s"]) - float(entry["start_s"])
                qa = float(entry.get("qa_score", 0))
                if entry.get("status") != "exported":
                    decision["reason"] = f"status {entry.get('status', 'missing')}"
                    continue
                if qa < config.outbox.min_qa or duration < 12:
                    decision["reason"] = (
                        "below min_qa" if qa < config.outbox.min_qa else "duration < 12s"
                    )
                    continue
                source = Path(entry["path"])
                if not source.is_absolute():
                    source = export_dir / source
                sfx = source.with_stem(source.stem + "_sfx")
                if sfx.is_file():
                    source = sfx
                key = f"{source.resolve()}|{source.stat().st_size}"
                if key in ledger:
                    decision.update(status="already copied", reason=ledger[key]["status"])
                    continue
                reasons = []
                if duration > 61:
                    reasons.append("duration > 61s")
                # Markdown may include extra review notes; restrict them to this clip's section.
                section = next(
                    (
                        s
                        for s in re.split(r"(?m)^## ", markdown)[1:]
                        if entry.get("title", "") in s.splitlines()[0]
                    ),
                    "",
                )
                notes = (
                    " ".join(entry.get("notes", []))
                    + " "
                    + " ".join(line for line in section.splitlines() if line.startswith("- note:"))
                )
                if re.search(r"\b(?:explicit|adult)\b", notes, re.IGNORECASE):
                    reasons.append("report notes mention explicit/adult content")
                if transcript is None:
                    reasons.append("transcript unavailable")
                else:
                    words = transcript.get("words") or transcript.get("segments", [])
                    text = " ".join(
                        w["text"]
                        for w in words
                        if float(w["end"]) > float(entry["start_s"])
                        and float(w["start"]) < float(entry["end_s"])
                    )
                    for pattern in config.outbox.block_keywords:
                        match = re.search(rf"\b(?:{pattern})\b", text, re.IGNORECASE)
                        if match:
                            reasons.append(f"blocked keyword: {match.group()}")
                status = "held" if reasons else "copied"
                target = _copy(source, root / ("held" if reasons else day), _caption(entry))
                platforms = config.upload_post.manual_platforms or config.post.platforms
                story = entry.get("story") or {}
                beats = "; ".join(
                    f"{beat}: {story.get(beat, {}).get('text', '')}" for beat in ("setup", "payoff")
                )
                reason = "; ".join(reasons)
                line = (
                    f"{'[dry-run] ' if dry_run else ''}{day}; platforms: {', '.join(platforms)}; "
                    f"QA: {qa:g}; duration: {duration:.2f}s; SFX: {entry.get('sfx') or 'none'}; "
                    f"job: {job_id}; VOD: {vod_id or 'unknown'}; {entry.get('title', '')}; "
                    f"{beats}; status: {status}{': ' + reason if reason else ''}; file: {target}"
                )
                with (root / "INDEX.md").open("a", encoding="utf-8") as handle:
                    handle.write(_one_line(line) + "\n")
                ledger[key] = {"date": day, "status": status, "path": str(target), "reason": reason}
                # Atomic replacement protects existing entries from interrupted writes.
                temporary = root / "outbox.json.tmp"
                temporary.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
                temporary.replace(ledger_path)
                decision.update(status=status, reason=reason, path=str(target))
            except Exception as exc:
                log.exception("Outbox failed for %s", decision["clip"])
                decision.update(status="error", reason=str(exc))
    except Exception:
        log.exception("Outbox failed for job %s", job_id)
    return results


def after_render(store: Any, config: AutoConfig, job: dict[str, Any], **kwargs: Any) -> None:
    """Read the refreshed job because the runner records the export directory in the store."""
    try:
        finished = store.get_job(job["id"])
        if finished and finished.get("state") == "done" and finished.get("export_dir"):
            export_job(
                Path(finished["export_dir"]),
                config,
                job_id=finished.get("autoclip_job_id") or "",
                vod_id=finished.get("vod_id") or "",
                **kwargs,
            )
    except Exception:
        log.exception("Outbox failed after render for job %s", job["id"])
