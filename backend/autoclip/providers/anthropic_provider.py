"""Anthropic (Claude) provider."""

from __future__ import annotations

import logging

from .base import DetectionConfig, LLMProvider, ProviderError, ProviderStatus
from .openai_provider import _translate

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"

#: Shown in the settings UI. Kept short and current rather than exhaustive.
SUGGESTED_MODELS = [
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
]


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    requires_key = True

    def __init__(self, model: str = "", *, api_key: str | None = None, base_url: str | None = None):
        super().__init__(model or DEFAULT_MODEL, api_key=api_key, base_url=base_url)

    def _client(self):
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - anthropic is a core dep
            raise ProviderError(
                "The anthropic package is not installed.", provider=self.name
            ) from exc

        if not self.api_key:
            raise ProviderError(
                "No Anthropic API key is set.",
                provider=self.name,
                hint="Add one with `autoclip config set-secret anthropic`.",
            )

        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return AsyncAnthropic(**kwargs, max_retries=0, timeout=60.0)

    async def _complete(
        self, system: str, user: str, config: DetectionConfig, *, json_mode: bool = True
    ) -> str:
        client = self._client()
        try:
            message = await client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=config.temperature,
                system=system,
                messages=[
                    {"role": "user", "content": user},
                    *([{"role": "assistant", "content": "{"}] if json_mode else []),
                ],
            )
        except Exception as exc:
            raise _translate(exc, self.name, self.model) from exc

        text = "".join(block.text for block in message.content if hasattr(block, "text"))
        return ("{" if json_mode else "") + text

    async def health_check(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(
                name=self.name, available=False, detail="No API key set", models=SUGGESTED_MODELS
            )
        try:
            client = self._client()
            await client.messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ok"}],
            )
        except Exception as exc:
            return ProviderStatus(
                name=self.name, available=False, detail=str(exc)[:200], models=SUGGESTED_MODELS
            )
        return ProviderStatus(
            name=self.name, available=True, detail=self.model, models=SUGGESTED_MODELS
        )
