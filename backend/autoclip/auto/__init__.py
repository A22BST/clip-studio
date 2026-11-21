"""Automation layer for Clip Studio (plan section 5): watch -> job -> select -> render ->
Telegram approval -> post (Upload-Post) -> track -> learn.

Safety model (read ``gate.py`` first): every upload goes through ``gate.check_post_allowed``,
which fails closed. Level 1 (default) needs a human Approve tap in the configured Telegram chat.
"""

from .secrets import harden_logging as _harden_logging

_harden_logging()
