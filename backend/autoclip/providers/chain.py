"""Provider-account buckets with model fallback and persisted daily reservations."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .. import paths
from ..auto.config import auto_dir
from ..config import ChainEntry, Settings, get_secret, load
from .anthropic_provider import AnthropicProvider
from .base import DetectionConfig, ProviderError
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider, _translate
from .presets import PRESETS

log = logging.getLogger(__name__)
_COOLDOWNS: dict[str, float] = {}


@dataclass(frozen=True)
class ChainResult:
    provider: str
    model: str


def resolve_entry(entry: ChainEntry) -> ChainEntry:
    values = PRESETS.get(entry.preset or "", {})
    if entry.preset and not values:
        raise ProviderError(f"Unknown chain preset: {entry.preset}")
    models = entry.models or ([entry.model] if entry.model else values.get("models", []))
    resolved = ChainEntry(
        name=entry.name,
        preset=entry.preset,
        base_url=entry.base_url or values.get("base_url"),
        models=models,
        model=models[0] if models else "",
        key_name=entry.key_name or values.get("key_name", entry.name),
        daily_requests=(
            entry.daily_requests
            if entry.daily_requests is not None
            else values.get("daily_requests")
        ),
        reset=entry.reset or values.get("reset", "utc"),
        max_prompt_tokens=entry.max_prompt_tokens or values.get("max_prompt_tokens"),
    )
    # Validate timezone before making calls (including on Windows with tzdata).
    ZoneInfo("UTC" if resolved.reset.lower() == "utc" else resolved.reset)
    if resolved.name.lower() not in {"anthropic", "claude", "ollama"} and (
        not resolved.base_url or not resolved.models
    ):
        raise ProviderError(f"Chain entry {entry.name} needs a base_url and model.")
    return resolved


def _identity(entry: ChainEntry) -> str:
    # Names/models may change; one endpoint and credential still share one account.
    return json.dumps([entry.base_url or entry.name, entry.key_name])


@contextmanager
def _usage_file():
    """Serialize read-modify-replace across processes using a stable sibling lock."""
    path = auto_dir() / "chain-usage.json"
    with path.with_suffix(".lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not isinstance(data, dict):
                raise ValueError("Expected usage object")
            yield data
            temp = path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(temp, path)
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def usage(entry: ChainEntry, *, reserve: bool = False, spent: bool = False) -> dict:
    """Atomically reserve before dispatch, including requests that subsequently fail.

    Persist a spent marker separately: unknown daily limits can still be exhausted.
    Unreadable state fails closed instead of silently losing the daily allowance.
    """
    zone = ZoneInfo("UTC" if (entry.reset or "utc").lower() == "utc" else entry.reset)
    day = datetime.fromtimestamp(time.time(), zone).date().isoformat()
    try:
        with _usage_file() as data:
            record = data.get(_identity(entry), {})
            if record.get("day") != day:
                record = {"day": day, "used": 0, "spent": False}
            allowed = not record["spent"] and (
                entry.daily_requests is None or record["used"] < entry.daily_requests
            )
            if reserve and allowed:
                record["used"] += 1
            if spent:
                record["spent"] = True
            data[_identity(entry)] = record
            return {**record, "allowed": allowed}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProviderError(
            "Cannot read/write chain daily usage; skipping calls.", provider="chain", kind="usage"
        ) from exc


class _AccountOpenAIProvider(OpenAIProvider):
    """Charge any adapter-level retry as well as the initial reservation.

    The shared adapter may retry an unsupported-parameter response even in
    plain chat mode. Keep that extra HTTP call inside the same account budget.
    """

    def __init__(self, *args, usage_entry: ChainEntry, **kwargs):
        super().__init__(*args, **kwargs)
        self.usage_entry = usage_entry

    def _client(self):
        client = super()._client()
        create = client.chat.completions.create
        dispatched = False

        async def counted_create(**kwargs):
            nonlocal dispatched
            if dispatched and not usage(self.usage_entry, reserve=True)["allowed"]:
                raise ProviderError("Daily quota spent before adapter retry.", kind="quota")
            dispatched = True
            return await create(**kwargs)

        client.chat.completions.create = counted_create
        return client


def _daily_quota(exc: ProviderError) -> bool:
    # OpenAIProvider preserves the upstream exception as __cause__. Inspect only;
    # never log it, since upstream text may contain credentials.
    detail = str(exc) + " " + str(exc.__cause__ or "")
    detail = detail.lower()
    return any(
        marker in detail
        for marker in (
            "daily",
            "per day",
            "per_day",
            "perday",
            "requests/day",
            "tokens/day",
            "rpd",
            "tpd",
        )
    )


def gpu_idle() -> bool:
    """Conservative existing indicators: scheduler heavy-work lock and running jobs.

    Missing/unreadable DB means unknown. Any tick lock is busy/unknown, including
    stale locks: this deliberately favours hosted fallbacks over GPU contention.
    """
    try:
        if (auto_dir() / "tick.lock").exists() or not paths.db_path().is_file():
            return False
        with closing(sqlite3.connect(paths.db_path().as_uri() + "?mode=ro", uri=True)) as conn:
            return (
                conn.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone() is None
            )
    except (OSError, sqlite3.Error):
        return False


class ChainProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings if settings is not None else load()
        self.config = self.settings.chain
        entries = [resolve_entry(e) for e in self.config.entries]
        hosted = [e for e in entries if not self._is_claude(e) and e.name.lower() != "ollama"]
        local = [e for e in entries if e.name.lower() == "ollama" and not self._is_claude(e)]
        self.entries = hosted + local
        if self.config.allow_claude:
            self.entries += [e for e in entries if self._is_claude(e)] or [
                ChainEntry(name="anthropic", key_name="anthropic")
            ]
        for entry in self.entries:
            if not entry.models and entry.name.lower() in {"anthropic", "claude", "ollama"}:
                name = "ollama" if entry.name.lower() == "ollama" else "anthropic"
                entry.model = self.settings.provider(name).model
                if not entry.model and name == "anthropic":
                    entry.model = AnthropicProvider().model
                entry.models = [entry.model] if entry.model else []
                if (
                    name == "ollama"
                    and self.settings.provider(name).base_url
                    and entry.base_url in {None, PRESETS["ollama"]["base_url"]}
                ):
                    entry.base_url = self.settings.provider(name).base_url
        self._bad: dict[ChainResult, int] = {}

    @staticmethod
    def _is_claude(entry: ChainEntry) -> bool:
        return (
            entry.name.lower() in {"anthropic", "claude"}
            or any("claude" in model.lower() for model in [entry.model, *entry.models])
            or "anthropic" in (entry.base_url or "").lower()
        )

    def reject(self, result: ChainResult) -> None:
        self._bad[result] = self._bad.get(result, 0) + 1

    def complete_text(self, system: str, user: str) -> tuple[str, ChainResult]:
        """Plain text chat; caller owns schema validation."""
        return asyncio.run(self._complete_text(system, user))

    def complete_validated(self, system, user, validate, *, max_attempts=None):
        """Repair malformed responses up to the per-model attempt limit."""
        limit = min(max_attempts or self.config.malformed_attempts, self.config.malformed_attempts)
        attempts = {}
        feedback = ""
        for _ in range(sum(len(e.models) for e in self.entries) * limit):
            text, result = self.complete_text(system, user + feedback)
            try:
                validate(text)
                return text, result
            except ValueError as exc:
                self.reject(result)
                attempts[result] = attempts.get(result, 0) + 1
                if attempts[result] >= limit:
                    self._bad[result] = self.config.malformed_attempts
                feedback = (
                    "\nYour previous response was invalid: "
                    + str(exc)[:2000]
                    + "\nReturn only corrected JSON. No prose or code fences."
                )
        raise ProviderError("All chain replies failed validation.", kind="malformed")

    async def _complete_text(self, system: str, user: str) -> tuple[str, ChainResult]:
        for entry in self.entries:
            identity = _identity(entry)
            local = entry.name.lower() == "ollama"
            prompt_tokens = (len(system) + len(user) + 3) // 4
            if entry.max_prompt_tokens and prompt_tokens > entry.max_prompt_tokens:
                log.info("Skipping chain bucket %s: prompt exceeds token guard", entry.name)
                continue
            if _COOLDOWNS.get(identity, 0) > time.monotonic():
                log.info("Skipping chain bucket %s during cooldown", entry.name)
                continue
            if local and not gpu_idle():
                log.info("Skipping ollama: GPU busy or idle state unknown")
                continue
            key = None if local else get_secret(entry.key_name, self.settings)
            if not local and not key:
                log.info("Skipping chain bucket %s: add key %s", entry.name, entry.key_name)
                continue
            base_url = entry.base_url
            if base_url and "{account_id}" in base_url:
                account_id = get_secret("cloudflare-account-id", self.settings)
                if not account_id:
                    log.info("Skipping chain bucket %s: add cloudflare-account-id", entry.name)
                    continue
                base_url = base_url.replace("{account_id}", account_id)
            for model in entry.models:
                result = ChainResult(entry.name, model)
                if self._bad.get(result, 0) >= self.config.malformed_attempts:
                    continue
                if not usage(entry, reserve=True)["allowed"]:
                    log.info("Skipping chain bucket %s: daily budget spent", entry.name)
                    break
                cls = (
                    OllamaProvider
                    if local
                    else AnthropicProvider
                    if entry.name.lower() in {"anthropic", "claude"}
                    else _AccountOpenAIProvider
                )
                provider_kwargs = {"usage_entry": entry} if cls is _AccountOpenAIProvider else {}
                provider = cls(model, api_key=key, base_url=base_url, **provider_kwargs)
                try:
                    kwargs = {} if local else {"json_mode": False}
                    text = await provider._complete(system, user, DetectionConfig(), **kwargs)
                except ProviderError as exc:
                    kind = exc.kind
                    if kind == "unknown" and exc.__cause__ is not None:
                        if isinstance(exc.__cause__, httpx.ConnectError):
                            kind = "connection"
                        elif isinstance(exc.__cause__, httpx.TimeoutException):
                            kind = "timeout"
                        else:
                            kind = _translate(exc.__cause__, entry.name, model).kind
                    if kind == "unknown":
                        kind = _translate(exc, entry.name, model).kind
                    if kind == "unknown" and "returned no choices" in str(exc):
                        kind = "malformed"
                    if kind in {"model", "malformed"}:
                        self._bad[result] = self.config.malformed_attempts
                        continue
                    if kind not in {"rate_limit", "quota", "connection", "timeout", "auth"}:
                        raise
                    if kind in {"rate_limit", "quota"}:
                        if _daily_quota(exc):
                            usage(entry, spent=True)
                        else:
                            _COOLDOWNS[identity] = time.monotonic() + self.config.cooldown_seconds
                    if kind == "auth":
                        log.warning(
                            "Chain bucket %s rejected authentication; add key %s",
                            entry.name,
                            entry.key_name,
                        )
                    else:
                        log.info("Skipping chain bucket %s: %s", entry.name, kind)
                    break
                if not text.strip():
                    self._bad[result] = self.config.malformed_attempts
                    continue
                log.info("Chain response from %s model %s", result.provider, result.model)
                return text, result
        raise ProviderError("No usable chain entries remain.", provider="chain", kind="exhausted")


def build_chain(settings: Settings | None = None) -> ChainProvider:
    return ChainProvider(settings)
