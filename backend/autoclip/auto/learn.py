"""Step 3e: the weekly learn-and-report job.

Collects what the store knows (approval rates, views per post, which hooks/layouts did well),
asks Claude (Sonnet, no tools) to turn it into (a) a short 'what works' rules file that the
headless /clip run reads next time and (b) a short earnings report sent to Telegram.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import claude_cli
from .campaign_meta import load_auto_campaign
from .config import AutoConfig
from .notify import Notifier
from .select import REPO_ROOT, what_works_path
from .store import Store, parse_iso

PROMPT = """\
You are the weekly analyst for a GTA 6 stream-clipping side business. Below is JSON about the
last {days} days. Reply with EXACTLY two sections and nothing else:

## WHAT_WORKS
At most 12 short bullet rules for the clip picker (hook style, length, layout, spoiler level,
topics that got more or fewer views, what Ahmad rejected). Only claim patterns the data supports;
if there is too little data, say so in one bullet and keep the previous rules that still make sense.

## REPORT
At most 10 lines for Telegram: clips posted, total views, estimated earnings, best and worst clip,
approval rate, one concrete suggestion. Plain text, no markdown tables.

Previous rules:
{previous}

DATA:
{data}
"""


def collect_stats(store: Store, now: datetime | None = None, days: int = 7) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    clips = store.list_clips()
    recent = [c for c in clips if (parse_iso(c["created_at"]) or now) >= since]
    by_status: dict[str, int] = {}
    for c in recent:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    decided = (
        by_status.get("approved", 0) + by_status.get("posted", 0) + by_status.get("rejected", 0)
    )
    approved = by_status.get("approved", 0) + by_status.get("posted", 0)
    rows = []
    total_views = 0
    earnings = 0.0
    for post in store.list_posts("posted"):
        clip = store.get_clip(post["clip_id"])
        if not clip:
            continue
        metrics = store.latest_metrics(post["id"])
        views = sum(m["views"] for m in metrics.values())
        try:
            rate = load_auto_campaign(clip["campaign_key"]).campaign.rate_per_1k_usd
        except Exception:
            rate = 0.0
        total_views += views
        earnings += views / 1000 * rate
        rows.append(
            {
                "title": clip["title"], "hook": clip["hook"], "layout": clip["layout"],
                "spoiler_level": clip["spoiler_level"], "qa": clip["qa_score"],
                "duration_s": round(clip["duration_s"]), "views": views,
                "per_platform": {p: m["views"] for p, m in metrics.items()},
                "posted_at": post["posted_at"],
            }
        )  # fmt: skip
    rows.sort(key=lambda r: r["views"], reverse=True)
    return {
        "days": days,
        "clips_by_status": by_status,
        "approval_rate": round(approved / decided, 2) if decided else None,
        "posted_total": len(rows),
        "total_views": total_views,
        "estimated_usd": round(earnings, 2),
        "best": rows[:3],
        "worst": rows[-3:] if len(rows) > 3 else [],
        "all_posted": rows[:30],
    }


def split_sections(text: str) -> tuple[str, str]:
    works, report = "", ""
    if "## REPORT" in text:
        head, report = text.split("## REPORT", 1)
        works = head.replace("## WHAT_WORKS", "").strip()
    return works.strip(), report.strip()


def run_weekly(
    store: Store,
    config: AutoConfig,
    notifier: Notifier,
    *,
    runner=None,
    now: datetime | None = None,
    works_path: Path | None = None,
) -> str:
    stats = collect_stats(store, now)
    works_file = works_path or what_works_path()
    previous = works_file.read_text(encoding="utf-8") if works_file.is_file() else "(none yet)"
    kwargs = {"runner": runner} if runner else {}
    result = claude_cli.run_claude(
        PROMPT.format(days=stats["days"], previous=previous, data=json.dumps(stats, indent=1)),
        model="sonnet",
        cwd=REPO_ROOT,
        allowed_tools=[],
        max_turns=3,
        timeout_s=600,
        **kwargs,
    )
    works, report = split_sections(result.text)
    if not report:
        report = (
            f"Weekly report: model returned no report (exit {result.returncode}). Raw stats: "
            + (
                f"{stats['posted_total']} posted, {stats['total_views']} views, ~${stats['estimated_usd']}"
            )
        )
    if works:
        works_file.parent.mkdir(parents=True, exist_ok=True)
        works_file.write_text(works + "\n", encoding="utf-8")
    notifier.send_text("Weekly report\n\n" + report)
    store.log_event("weekly", f"{stats['posted_total']} posted, {stats['total_views']} views")
    return report
