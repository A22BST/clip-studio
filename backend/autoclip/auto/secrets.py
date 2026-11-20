"""Secrets come from the environment, falling back to the Windows *user* environment.

A variable set with ``setx`` is invisible to an already running process, so a scheduled task
started earlier may need ``HKCU\\Environment``. Values are returned to the caller only: they
must never be printed, logged, stored in the database or put in an exception message.
"""

from __future__ import annotations

import os

TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"
UPLOAD_POST_API_KEY = "UPLOAD_POST_API_KEY"
DISCORD_BOT_TOKEN = "DISCORD_BOT_TOKEN"
DISCORD_CHANNEL_ID = "DISCORD_CHANNEL_ID"
DISCORD_OWNER_ID = "DISCORD_OWNER_ID"
TWITCH_CLIENT_ID = "TWITCH_CLIENT_ID"
TWITCH_CLIENT_SECRET = "TWITCH_CLIENT_SECRET"


class MissingSecretError(RuntimeError):
    """A required secret is not set. The message names the variable, never a value."""


def get_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            registry_value, _kind = winreg.QueryValueEx(key, name)
            text = str(registry_value).strip()
            return text or None
    except (ImportError, OSError):
        return None


def require_secret(name: str) -> str:
    value = get_secret(name)
    if not value:
        raise MissingSecretError(
            f"{name} is not set. Set it as a Windows User environment variable "
            f"(or in the process environment)."
        )
    return value


def secret_is_set(name: str) -> bool:
    return get_secret(name) is not None
