"""Validate campaign files before their rules can approve a clip."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Campaign(BaseModel):
    """Reject misspelled rules rather than silently weakening a campaign."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1)
    platforms: list[Literal["tiktok", "youtube", "instagram"]] = Field(default_factory=list)
    min_duration_s: float = Field(default=0, ge=0)
    max_duration_s: float = Field(default=90, gt=0)
    required_hashtags: list[str] = Field(default_factory=list)
    required_mentions: list[str] = Field(default_factory=list)
    banned_words: list[str] = Field(default_factory=list)
    banned_topics: list[str] = Field(default_factory=list)
    max_title_chars: int = Field(default=100, ge=1)
    today_only: bool = False
    max_age_hours: float = Field(default=24, gt=0)
    spoiler_policy: Literal["light", "strict", "none"] = "light"
    swear_filter: Literal["off", "bleep", "mask"] = "off"
    rate_per_1k_usd: float = Field(default=0, ge=0)
    notes: str = ""
    #: "cpm" pays per approved view; "prize_pool" campaigns have view minimums and geo rules.
    type: Literal["cpm", "prize_pool"] = "cpm"
    #: Minutes allowed between posting and submitting to the campaign (Content Rewards: 30).
    #: Informational for rendering; the later automation must submit/alert within it.
    submit_deadline_min: int = Field(default=30, ge=1)
    #: Paid-partnership label shown at the start of every clip (e.g. "#ad").
    disclosure_required: bool = False
    disclosure_text: str = "#ad  Paid partnership"
    disclosure_duration_s: float = Field(default=3.0, gt=0, le=10)
    #: A streamer logo/watermark that must be visible for the ENTIRE clip. Name of an
    #: image under campaigns/assets/ (or an absolute path). Empty = not required.
    required_overlay: str = ""
    #: Phrases the post caption must contain (case-insensitive), e.g. a "Watch X" line.
    required_caption_phrases: list[str] = Field(default_factory=list)
    #: Campaign forbids AI-generated video/logos. We never generate any; kept as a record.
    no_ai_visuals: bool = False
    #: Free-text audience-country requirement (checked by a human, not the renderer).
    audience_geo: str = ""
    min_engagement_pct: float = Field(default=0, ge=0)
    max_similar_posts: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def accept_required_tags_alias(cls, data):
        """``required_tags`` is accepted as another name for ``required_hashtags``."""
        if isinstance(data, dict) and "required_tags" in data:
            data = dict(data)
            extra = data.pop("required_tags") or []
            data["required_hashtags"] = [*(data.get("required_hashtags") or []), *extra]
        return data

    @model_validator(mode="after")
    def duration_range(self) -> Self:
        """An inverted range would make every submitted clip fail."""
        if self.min_duration_s > self.max_duration_s:
            raise ValueError("min_duration_s must be <= max_duration_s")
        return self


def load_campaign(name_or_path: str | Path, campaigns_dir: str | Path | None = None) -> Campaign:
    """Resolve names from the checkout; installed packages can override the directory."""
    candidate = Path(name_or_path)
    directory = Path(
        campaigns_dir
        or os.environ.get("CLIPSTUDIO_CAMPAIGNS_DIR")
        or Path(__file__).resolve().parents[3] / "campaigns"
    )
    if candidate.is_absolute() or candidate.parent != Path("."):
        path = candidate
    else:
        path = directory / candidate
    if not path.suffix:
        path = path.with_suffix(".yaml")
    if not path.is_file():
        raise FileNotFoundError(f"Campaign file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Campaign.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        fields = ", ".join(Campaign.model_fields)
        raise ValueError(f"Invalid campaign {path}: {exc}. Valid fields: {fields}") from exc
