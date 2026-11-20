"""``posted_to_submit.csv``: every posted URL with its Content Rewards deadline, one row each."""

from __future__ import annotations

import csv
from pathlib import Path

from .campaign_meta import load_auto_campaign
from .config import AutoConfig, auto_dir
from .publisher import MANUAL_URL
from .store import Store

COLUMNS = ["posted_at", "submit_deadline", "campaign", "platform", "url", "title", "submit_url"]


def csv_path() -> Path:
    return auto_dir() / "posted_to_submit.csv"


def append_posted(
    store: Store, config: AutoConfig | None, post_id: int, path: Path | None = None
) -> int:
    """Append rows for the post's real URLs that are not in the file yet. Returns rows added."""
    path = path or csv_path()
    post = store.get_post(post_id)
    if not post or post["status"] != "posted":
        return 0
    clip = store.get_clip(post["clip_id"])
    if not clip:
        return 0
    try:
        submit_url = load_auto_campaign(clip["campaign_key"]).meta.submit_url
    except Exception:
        submit_url = ""
    known: set[str] = set()
    if path.is_file():
        with open(path, encoding="utf-8", newline="") as handle:
            known = {r["url"] for r in csv.DictReader(handle)}
    new = [
        {
            "posted_at": post["posted_at"],
            "submit_deadline": post["submit_deadline"],
            "campaign": clip["campaign_key"],
            "platform": platform,
            "url": r["url"],
            "title": clip["title"],
            "submit_url": submit_url,
        }
        for platform, r in post["results"].items()
        if r.get("url", "").startswith("http") and r["url"] != MANUAL_URL and r["url"] not in known
    ]
    if not new:
        return 0
    fresh = not path.is_file()
    with open(path, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if fresh:
            writer.writeheader()
        writer.writerows(new)
    return len(new)
