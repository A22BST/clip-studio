"""Automation metadata per campaign, kept in a sidecar so ``stream/campaigns.py`` stays untouched.

``campaigns/<stem>.yaml`` holds the clip rules (session 1's strict ``Campaign`` model).
``campaigns/auto/<stem>.yaml`` says which streamers to watch and whether the campaign is
live. A campaign WITHOUT a sidecar is never automated (the placeholder ``-test`` campaign
has none on purpose).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..stream.campaigns import Campaign, load_campaign


class BackfillConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_slices_per_tick: int = Field(default=1, ge=0)
    max_hours_per_day: float = Field(default=6, gt=0)


class AutoMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    streamers: list[str] = Field(default_factory=list)  # Twitch logins or YouTube @handles
    platform: str = "twitch"
    active: bool = True
    ends_at: date | None = None
    starts_at: date | None = None  # Earliest eligible source stream date (UTC).
    budget_usd: float | None = Field(default=None, gt=0)
    #: Max payout per clip (per post): the budget estimate never counts more than this for one post.
    cap_per_clip_usd: float | None = Field(default=None, gt=0)
    submit_url: str = ""
    notes: str = ""
    backfill: BackfillConfig = Field(default_factory=BackfillConfig)


@dataclass
class AutoCampaign:
    key: str  # file stem, e.g. "kreekcraft-gta6"
    campaign: Campaign
    meta: AutoMeta
    path: Path = field(default_factory=Path)

    def is_live(self, now: datetime | None = None) -> tuple[bool, str]:
        if not self.meta.active:
            return False, "campaign is switched off (active: false)"
        if self.meta.ends_at is not None:
            today = (now or datetime.now(UTC)).date()
            if today > self.meta.ends_at:
                return False, f"campaign ended on {self.meta.ends_at}"
        return True, ""


def campaigns_dir() -> Path:
    return Path(
        os.environ.get("CLIPSTUDIO_CAMPAIGNS_DIR")
        or Path(__file__).resolve().parents[3] / "campaigns"
    )


def load_auto_campaign(key: str, directory: Path | None = None) -> AutoCampaign:
    """Load rules + sidecar. Raises FileNotFoundError when either is missing."""
    directory = directory or campaigns_dir()
    campaign = load_campaign(key, campaigns_dir=directory)
    sidecar = directory / "auto" / f"{key}.yaml"
    if not sidecar.is_file():
        raise FileNotFoundError(f"No automation sidecar for campaign {key!r}: {sidecar}")
    meta = AutoMeta.model_validate(yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {})
    return AutoCampaign(key=key, campaign=campaign, meta=meta, path=directory / f"{key}.yaml")


def load_all_auto_campaigns(directory: Path | None = None) -> list[AutoCampaign]:
    """Every campaign with a valid sidecar. Broken files are skipped."""
    directory = directory or campaigns_dir()
    found: list[AutoCampaign] = []
    for sidecar in sorted((directory / "auto").glob("*.yaml")):
        try:
            found.append(load_auto_campaign(sidecar.stem, directory))
        except Exception:
            continue
    return found
