"""The publishing backend interface. Upload-Post is the default; others can be added later.

Only ``poster.post_due`` calls a publisher, and only after ``gate.check_post_allowed`` allowed
the post. Platforms the plan or account cannot post to automatically are listed in
``config.upload_post.manual_platforms`` and handled as hand-posts (file + caption sent to chat).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

MANUAL_URL = "(posted by hand)"


class Publisher(Protocol):
    def upload(
        self,
        video_path: Path | str,
        platforms: list[str],
        title: str,
        caption: str,
        hashtags: list[str],
        campaign: Any,
        idempotency_key: str,
    ) -> Any: ...

    def status(self, request_id: str) -> Any: ...

    def history(self, request_id: str) -> Any: ...

    def post_analytics(self, request_id: str) -> dict[str, Any]: ...


def split_platforms(platforms: list[str], manual: list[str]) -> tuple[list[str], list[str]]:
    """(platforms the API posts, platforms Ahmad posts by hand)."""
    manual_set = {m.lower() for m in manual}
    return (
        [p for p in platforms if p.lower() not in manual_set],
        [p for p in platforms if p.lower() in manual_set],
    )
