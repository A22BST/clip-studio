"""Automation settings: ``<root>/auto/config.yaml`` (every field optional, safe defaults).

Level 2 (post without a tap) is OFF by default and needs BOTH ``level: 2`` and
``auto_approve.enabled: true`` in this file. There is no CLI flag, no environment variable
and no Telegram command that turns it on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import paths


def auto_dir() -> Path:
    path = paths.root() / "auto"
    path.mkdir(parents=True, exist_ok=True)
    return path


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AutoApprove(_Section):
    enabled: bool = False
    #: Clips at or above this QA score may post without a tap (level 2 only).
    min_qa: int = Field(default=90, ge=1, le=100)
    #: Minutes between approval and posting so Ahmad can delete it.
    delay_minutes: int = Field(default=60, ge=1)


class PostConfig(_Section):
    #: Local clock times (HH:MM, in ``timezone``) at which a post may go out.
    slots: list[str] = ["11:00", "14:00", "17:30", "20:00", "22:00"]
    timezone: str = "Europe/Copenhagen"
    max_per_day: int = Field(default=4, ge=1)
    min_gap_minutes: int = Field(default=90, ge=1)
    platforms: list[str] = ["tiktok", "youtube", "instagram"]
    #: An approved-but-unposted clip older than this is expired, never posted.
    approval_ttl_hours: float = Field(default=48, gt=0)

    @field_validator("slots")
    @classmethod
    def _slots(cls, value: list[str]) -> list[str]:
        for slot in value:
            hh, mm = slot.split(":")
            if not (0 <= int(hh) < 24 and 0 <= int(mm) < 60):
                raise ValueError(f"bad slot {slot!r}")
        return sorted(value)


class UploadPostConfig(_Section):
    base_url: str = "https://api.upload-post.com"
    profile: str = "crazyheist"  # the Upload-Post profile ("user") holding the 3 accounts
    tiktok_privacy: str = "PUBLIC_TO_EVERYONE"
    tiktok_post_mode: str = "DIRECT_POST"  # MEDIA_UPLOAD would only create drafts
    youtube_privacy: str = "public"
    #: Platforms the Upload-Post plan cannot post (the free tier has no TikTok). They are not
    #: uploaded: the chat gets the file + caption to post by hand. Clear this after upgrading.
    manual_platforms: list[str] = ["tiktok"]


class WatchConfig(_Section):
    max_vod_age_hours: float = Field(default=48, gt=0)
    #: Longest piece of a VOD processed as one job (transcribing 3 h takes ~30 min here).
    slice_hours: float = Field(default=3.0, gt=0)
    max_slices_per_vod: int = Field(default=2, ge=1)
    wait_until_offline: bool = True
    baseline_on_first_run: bool = True


class DiskConfig(_Section):
    min_free_gb: float = Field(default=10.0, gt=0)


class SelectionConfig(_Section):
    model: str = "sonnet"
    timeout_min: int = Field(default=25, ge=1)
    max_attempts: int = Field(default=2, ge=1)
    max_turns: int = Field(default=40, ge=1)


class TrackerConfig(_Section):
    csv_path: str = ""  # default: <root>/auto/tracker.csv
    google_sheet_id: str = ""  # optional; needs Google credentials, not built yet


class AutoConfig(_Section):
    #: Where approvals happen. Discord is the default; Telegram stays as an alternative backend.
    chat: Literal["discord", "telegram"] = "discord"
    level: int = Field(default=1, ge=1, le=2)
    auto_approve: AutoApprove = AutoApprove()
    #: Clips under this QA score are never sent to Telegram.
    min_qa_to_send: int = Field(default=60, ge=0, le=100)
    post: PostConfig = PostConfig()
    upload_post: UploadPostConfig = UploadPostConfig()
    watch: WatchConfig = WatchConfig()
    disk: DiskConfig = DiskConfig()
    selection: SelectionConfig = SelectionConfig()
    tracker: TrackerConfig = TrackerConfig()
    #: Delete the downloaded VOD after a job finishes (exports are kept).
    delete_source_after_render: bool = True

    @property
    def level2_active(self) -> bool:
        return self.level == 2 and self.auto_approve.enabled

    def tracker_csv(self) -> Path:
        return Path(self.tracker.csv_path) if self.tracker.csv_path else auto_dir() / "tracker.csv"


def config_file() -> Path:
    return auto_dir() / "config.yaml"


def load_config(path: Path | None = None) -> AutoConfig:
    path = path or config_file()
    if not path.is_file():
        return AutoConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AutoConfig.model_validate(data)
