"""Chat-replay model shared by ingest (2a) and hype detection (2b).

Reads the JSON that ``TwitchDownloaderCLI chatdownload`` writes. Message times are
seconds from the START OF THE VOD (``content_offset_seconds``), which is the same
clock as the downloaded video file, so no further alignment is needed unless the
VOD was trimmed (``ChatLog.offset_s`` handles that).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ChatMessage:
    #: Seconds from the start of the video file this chat belongs to.
    t: float
    user: str
    text: str
    #: Emote names used in the message (Twitch emotes by name, e.g. "KEKW").
    emotes: list[str] = field(default_factory=list)


@dataclass
class ChatLog:
    messages: list[ChatMessage] = field(default_factory=list)
    streamer: str = ""
    #: Length of the video in seconds when known (0 if unknown).
    duration_s: float = 0.0
    video_id: str = ""

    def __len__(self) -> int:
        return len(self.messages)

    def between(self, start_s: float, end_s: float) -> list[ChatMessage]:
        """Messages with start_s <= t < end_s (messages are kept sorted by t)."""
        return [m for m in self.messages if start_s <= m.t < end_s]

    def shifted(self, offset_s: float) -> ChatLog:
        """A copy with every message time shifted by ``offset_s`` (negative = earlier).

        Use when the video file starts later than the original VOD: pass
        ``-trim_start_s`` so chat times line up with the trimmed file.
        """
        return ChatLog(
            messages=[
                ChatMessage(m.t + offset_s, m.user, m.text, list(m.emotes))
                for m in self.messages
                if m.t + offset_s >= 0
            ],
            streamer=self.streamer,
            duration_s=max(0.0, self.duration_s + offset_s),
            video_id=self.video_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "streamer": self.streamer,
            "duration_s": self.duration_s,
            "video_id": self.video_id,
            "messages": [
                {"t": m.t, "user": m.user, "text": m.text, "emotes": m.emotes}
                for m in self.messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatLog:
        return cls(
            messages=[ChatMessage(**m) for m in data.get("messages", [])],
            streamer=data.get("streamer", ""),
            duration_s=float(data.get("duration_s", 0.0)),
            video_id=str(data.get("video_id", "")),
        )

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> ChatLog:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def parse_twitchdownloader_json(raw: dict[str, Any]) -> ChatLog:
    """Convert TwitchDownloader's chat JSON (``comments`` list) into a ChatLog.

    Tolerant of missing fields: a malformed comment is skipped, never fatal.
    """
    messages: list[ChatMessage] = []
    for comment in raw.get("comments", []):
        try:
            t = float(comment["content_offset_seconds"])
            message = comment.get("message", {})
            text = message.get("body", "") or ""
            commenter = comment.get("commenter") or {}
            user = commenter.get("display_name") or commenter.get("name") or ""
            emotes = [
                f["text"]
                for f in message.get("fragments", []) or []
                if f.get("emoticon") and f.get("text")
            ]
        except (KeyError, TypeError, ValueError):
            continue
        messages.append(ChatMessage(t=t, user=user, text=text, emotes=emotes))

    messages.sort(key=lambda m: m.t)
    video = raw.get("video") or {}
    streamer = (raw.get("streamer") or {}).get("name", "")
    duration = float(video.get("length", 0.0) or 0.0)
    if not duration and video.get("end") is not None:
        duration = float(video.get("end", 0.0)) - float(video.get("start", 0.0) or 0.0)
    video_id = str(video.get("id", "") or "")
    if not video_id and raw.get("comments"):
        video_id = str(raw["comments"][0].get("content_id", "") or "")
    return ChatLog(messages=messages, streamer=streamer, duration_s=duration, video_id=video_id)


def load_twitchdownloader_json(path: Path) -> ChatLog:
    return parse_twitchdownloader_json(json.loads(Path(path).read_text(encoding="utf-8")))
