"""Automation settings: ``<root>/auto/config.yaml`` (every field optional, safe defaults).

Level 2 (post without a tap) needs BOTH ``level: 2`` and ``auto_approve.enabled: true`` in this
file. There is no CLI flag, no environment variable and no Telegram command that turns it on. The
code defaults stay at level 1 (fail closed when the file is missing); the decided fully automatic
mode ships as ``docs/auto-config.example.yaml`` (``clip-auto init-config``).
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
    delay_minutes: int = Field(default=60, ge=0)


class PostConfig(_Section):
    #: Local clock times (HH:MM, in ``timezone``) at which a post may go out.
    slots: list[str] = ["11:00", "14:00", "17:30", "20:00", "22:00"]
    timezone: str = "Europe/Copenhagen"
    #: Safety net across all platforms (3 platforms x 3 posts).
    max_per_day: int = Field(default=9, ge=1)
    min_gap_minutes: int = Field(default=90, ge=1)
    #: Posts per platform per day by account age: week 1, week 2, week 3 and later.
    per_platform_daily_caps: list[int] = [1, 2, 3]
    min_gap_hours_per_platform: float = Field(default=4.0, ge=0)
    jitter_minutes: int = Field(default=30, ge=0)
    #: The same clip goes to its platforms this many minutes apart (random in the range).
    stagger_minutes: tuple[int, int] = (60, 120)
    #: A clip that cannot be scheduled within this many hours of approval expires.
    queue_expiry_hours: float = Field(default=48, gt=0)
    #: Account start (YYYY-MM-DD) for the week counter; empty = first scheduled post.
    start_date: str = ""
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


class ThrottleConfig(_Section):
    enabled: bool = True
    #: Pause a platform when its last 3 posts average below this share of its 7-day average.
    drop_ratio: float = Field(default=0.2, gt=0, lt=1)
    pause_hours: float = Field(default=48, gt=0)


class UploadPostConfig(_Section):
    base_url: str = "https://api.upload-post.com"
    profile: str = "crazyheist"  # the Upload-Post profile ("user") holding the 3 accounts
    tiktok_privacy: str = "PUBLIC_TO_EVERYONE"
    tiktok_post_mode: str = "DIRECT_POST"  # MEDIA_UPLOAD would only create drafts
    youtube_privacy: str = "public"
    #: Platforms the Upload-Post plan cannot post (the FREE tier has no TikTok; Basic and up do).
    #: They are not uploaded: the chat gets the file + caption to post by hand. Default: none.
    manual_platforms: list[str] = []


class WatchConfig(_Section):
    max_vod_age_hours: float = Field(default=48, gt=0)
    #: Longest piece of a VOD processed as one job (transcribing 3 h takes ~30 min here).
    slice_hours: float = Field(default=3.0, gt=0)
    max_slices_per_vod: int = Field(default=2, ge=1)
    wait_until_offline: bool = True
    baseline_on_first_run: bool = True


class DiskConfig(_Section):
    min_free_gb: float = Field(default=10.0, gt=0)


class LearnConfig(_Section):
    backend: Literal["chain", "claude"] = "chain"


class SelectionConfig(_Section):
    backend: Literal["claude", "chain"] = "claude"
    model: str = "sonnet"
    timeout_min: int = Field(default=25, ge=1)
    max_attempts: int = Field(default=2, ge=1)
    max_turns: int = Field(default=40, ge=1)


class TrackerConfig(_Section):
    csv_path: str = ""  # default: <root>/auto/tracker.csv
    google_sheet_id: str = ""  # optional; needs Google credentials, not built yet


class SubmitConfig(_Section):
    #: Minutes after a post at which "submit now" is repeated until /submitted (deadline = 30 min).
    reminder_minutes: list[int] = [20]

    @field_validator("reminder_minutes")
    @classmethod
    def _minutes(cls, value: list[int]) -> list[int]:
        if any(m <= 0 for m in value):
            raise ValueError("reminder_minutes must be positive")
        return sorted(set(value))


class AutoConfig(_Section):
    #: The chat: one-way pings + /pause /resume /status /submitted. Telegram is the default;
    #: the Discord code is kept but is no longer part of the default path.
    chat: Literal["discord", "telegram"] = "telegram"
    level: int = Field(default=1, ge=1, le=2)
    auto_approve: AutoApprove = AutoApprove()
    #: Clips under this QA score are never sent to Telegram.
    min_qa_to_send: int = Field(default=60, ge=0, le=100)
    post: PostConfig = PostConfig()
    upload_post: UploadPostConfig = UploadPostConfig()
    watch: WatchConfig = WatchConfig()
    disk: DiskConfig = DiskConfig()
    selection: SelectionConfig = SelectionConfig()
    learn: LearnConfig = LearnConfig()
    tracker: TrackerConfig = TrackerConfig()
    throttle: ThrottleConfig = ThrottleConfig()
    submit: SubmitConfig = SubmitConfig()
    #: Delete the downloaded VOD after a job finishes (exports are kept).
    delete_source_after_render: bool = True

    @property
    def level2_active(self) -> bool:
        return self.level == 2 and self.auto_approve.enabled

    def mode_text(self) -> str:
        if self.level2_active:
            return (
                f"level 2 fully automatic (auto-approve QA >= {self.auto_approve.min_qa}, "
                f"review window {self.auto_approve.delay_minutes} min), chat {self.chat}"
            )
        return f"level {self.level}, human approval in {self.chat} (auto-approve off)"

    def tracker_csv(self) -> Path:
        return Path(self.tracker.csv_path) if self.tracker.csv_path else auto_dir() / "tracker.csv"


def config_file() -> Path:
    return auto_dir() / "config.yaml"


def example_config_file() -> Path:
    """The repo template ``docs/auto-config.example.yaml`` (the decided fully automatic mode)."""
    return Path(__file__).resolve().parents[3] / "docs" / "auto-config.example.yaml"


def init_config(path: Path | None = None, *, force: bool = False) -> Path:
    """Copy the template to ``~/.autoclip/auto/config.yaml``. Never overwrites without ``force``."""
    target = path or config_file()
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists (use --force to overwrite)")
    template = example_config_file()
    AutoConfig.model_validate(yaml.safe_load(template.read_text(encoding="utf-8")) or {})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def load_config(path: Path | None = None) -> AutoConfig:
    path = path or config_file()
    if not path.is_file():
        return AutoConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AutoConfig.model_validate(data)
