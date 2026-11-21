"""Discord notifications over the REST API (httpx), usable from any process (tick, poster, CLI).

The interactive side (buttons, slash commands, the edit-hook modal) lives in ``discord_bot.py``
and talks to Discord through the gateway, so no inbound port is opened on the laptop. This class
can only ever post to ``DISCORD_CHANNEL_ID``: the channel is not a parameter of any send method.
The bot token is never logged and never appears in an exception message.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from . import secrets
from .notify import Buttons, NotifyError, redact_paths

API = "https://discord.com/api/v10"
MAX_UPLOAD_BYTES = 9 * 1024 * 1024  # regular servers allow 10 MB per upload
PROFILE = "discord"

_STYLES = {"a": 3, "r": 4}  # a: Approve = green, r: Reject = red, everything else grey


def components(buttons: Buttons | None) -> list[dict[str, Any]]:
    rows = []
    for row in buttons or []:
        items = []
        for b in row[:5]:
            item: dict[str, Any] = {"type": 2, "label": b.text[:80]}
            if b.url:
                item |= {"style": 5, "url": b.url}
            else:
                data = b.callback_data or "noop"
                item |= {"style": _STYLES.get(data[:1], 2), "custom_id": data[:100]}
            items.append(item)
        if items:
            rows.append({"type": 1, "components": items})
    return rows[:5]


def split_caption(caption: str) -> tuple[str, str]:
    """First line becomes the embed title, the rest its description."""
    first, _, rest = caption.partition("\n")
    return first[:250], rest[:3900]


class DiscordNotifier:
    max_upload_bytes = MAX_UPLOAD_BYTES
    preview_profile = PROFILE

    def __init__(self, client: httpx.Client | None = None, timeout: float = 120.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def _post(self, **kwargs: Any) -> dict[str, Any]:
        token = secrets.require_secret(secrets.DISCORD_BOT_TOKEN)
        channel = secrets.require_secret(secrets.DISCORD_CHANNEL_ID)
        try:
            response = self._client.post(
                f"{API}/channels/{channel}/messages",
                headers={"Authorization": f"Bot {token}"},
                **kwargs,
            )
        except httpx.HTTPError as exc:  # drop the message: it could carry request details
            raise NotifyError(f"Discord send failed: {type(exc).__name__}") from None
        if response.status_code not in (200, 201):
            raise NotifyError(f"Discord send failed: HTTP {response.status_code}")
        return response.json()

    def send_text(self, text: str, buttons: Buttons | None = None) -> int | None:
        payload: dict[str, Any] = {"content": redact_paths(text)[:1990], "allowed_mentions": {"parse": []}}
        if buttons:
            payload["components"] = components(buttons)
        return int(self._post(json=payload)["id"])

    def send_video(self, path: Path, caption: str, buttons: Buttons | None = None) -> int | None:
        title, description = split_caption(redact_paths(caption))
        payload: dict[str, Any] = {
            "embeds": [{"title": title, "description": description, "color": 0x5865F2}],
            "allowed_mentions": {"parse": []},
        }
        if buttons:
            payload["components"] = components(buttons)
        with open(path, "rb") as handle:
            result = self._post(
                data={"payload_json": json.dumps(payload)},
                files={"files[0]": (Path(path).name, handle, "video/mp4")},
            )
        return int(result["id"])
