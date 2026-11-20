"""Telegram notifications over the plain Bot HTTP API (httpx), usable from any process.

The ``Notifier`` protocol is what the posting, tracking and approval code depends on, so tests
inject ``RecordingNotifier``. ``TelegramNotifier`` can only ever talk to the chat id in
``TELEGRAM_CHAT_ID``: the chat id is not a parameter of any send method. The bot token and chat
id are never logged and never appear in exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from . import secrets

API = "https://api.telegram.org"


@dataclass(frozen=True)
class Button:
    text: str
    callback_data: str | None = None
    url: str | None = None


Buttons = list[list[Button]]


class NotifyError(RuntimeError):
    pass


class Notifier(Protocol):
    def send_text(self, text: str, buttons: Buttons | None = None) -> int | None: ...

    def send_video(
        self, path: Path, caption: str, buttons: Buttons | None = None
    ) -> int | None: ...


def keyboard(buttons: Buttons | None) -> dict[str, Any] | None:
    if not buttons:
        return None
    rows = []
    for row in buttons:
        out = []
        for b in row:
            item: dict[str, Any] = {"text": b.text}
            if b.url:
                item["url"] = b.url
            else:
                item["callback_data"] = b.callback_data or "noop"
            out.append(item)
        rows.append(out)
    return {"inline_keyboard": rows}


class TelegramNotifier:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 120.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def _call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        token = secrets.require_secret(secrets.TELEGRAM_BOT_TOKEN)
        try:
            response = self._client.post(f"{API}/bot{token}/{method}", **kwargs)
        except httpx.HTTPError as exc:  # message could contain the URL (= the token): drop it
            raise NotifyError(f"Telegram {method} failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise NotifyError(f"Telegram {method} failed: HTTP {response.status_code}")
        return response.json().get("result", {})

    def send_text(self, text: str, buttons: Buttons | None = None) -> int | None:
        chat_id = secrets.require_secret(secrets.TELEGRAM_CHAT_ID)
        data: dict[str, Any] = {"chat_id": chat_id, "text": text[:4000]}
        markup = keyboard(buttons)
        if markup:
            data["reply_markup"] = markup
        result = self._call("sendMessage", json=data)
        return result.get("message_id")

    def send_video(self, path: Path, caption: str, buttons: Buttons | None = None) -> int | None:
        import json

        chat_id = secrets.require_secret(secrets.TELEGRAM_CHAT_ID)
        data = {"chat_id": chat_id, "caption": caption[:1000], "supports_streaming": "true"}
        markup = keyboard(buttons)
        if markup:
            data["reply_markup"] = json.dumps(markup)
        with open(path, "rb") as handle:
            result = self._call(
                "sendVideo", data=data, files={"video": (Path(path).name, handle, "video/mp4")}
            )
        return result.get("message_id")


@dataclass
class RecordingNotifier:
    """Test double: remembers every message instead of sending it."""

    texts: list[tuple[str, Buttons | None]] = field(default_factory=list)
    videos: list[tuple[Path, str, Buttons | None]] = field(default_factory=list)
    _next_id: int = 100

    def send_text(self, text: str, buttons: Buttons | None = None) -> int | None:
        self.texts.append((text, buttons))
        self._next_id += 1
        return self._next_id

    def send_video(self, path: Path, caption: str, buttons: Buttons | None = None) -> int | None:
        self.videos.append((Path(path), caption, buttons))
        self._next_id += 1
        return self._next_id


class CompositeNotifier:
    """Primary chat (approvals, previews, hand-posts) plus a one-way text ping.

    Text messages also go to ``ping`` WITHOUT buttons (it has no callbacks). Videos and previews go
    to the primary only. A failing ping never breaks the primary send or the pipeline.
    """

    def __init__(self, primary: Notifier, ping: Notifier) -> None:
        self.primary, self.ping = primary, ping
        self.max_upload_bytes = getattr(primary, "max_upload_bytes", 45 * 1024 * 1024)
        self.preview_profile = getattr(primary, "preview_profile", "telegram")

    def send_text(self, text: str, buttons: Buttons | None = None) -> int | None:
        result = self.primary.send_text(text, buttons)
        try:
            self.ping.send_text(text)
        except Exception:  # noqa: BLE001 - the ping is best effort
            pass
        return result

    def send_video(self, path: Path, caption: str, buttons: Buttons | None = None) -> int | None:
        return self.primary.send_video(path, caption, buttons)
