"""OpenAI-compatible provider.

Deliberately the widest adapter in AutoClip. Because ``base_url`` is
configurable and the Chat Completions shape is a de-facto standard, this one
class also covers OpenRouter, Groq, DeepSeek, Together, Fireworks, vLLM, and a
local LM Studio server. "Bring any API key" is mostly this file.
"""

from __future__ import annotations

import logging

from .base import DetectionConfig, LLMProvider, ProviderError, ProviderStatus

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o"

SUGGESTED_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "o4-mini",
]

#: Ready-made endpoints for the settings UI. Users can enter any other URL.
KNOWN_ENDPOINTS = {
    "OpenAI": "https://api.openai.com/v1",
    "OpenRouter": "https://openrouter.ai/api/v1",
    "Groq": "https://api.groq.com/openai/v1",
    "DeepSeek": "https://api.deepseek.com/v1",
    "Together": "https://api.together.xyz/v1",
    "LM Studio (local)": "http://localhost:1234/v1",
}


class OpenAIProvider(LLMProvider):
    name = "openai"
    requires_key = True

    def __init__(self, model: str = "", *, api_key: str | None = None, base_url: str | None = None):
        super().__init__(model or DEFAULT_MODEL, api_key=api_key, base_url=base_url)

    def _client(self):
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - openai is a core dep
            raise ProviderError("The openai package is not installed.", provider=self.name) from exc

        # Local servers ignore the key but the SDK still requires a non-empty
        # value, so supply a placeholder rather than failing the request.
        key = self.api_key or ("not-needed" if self._is_local() else None)
        if not key:
            raise ProviderError(
                "No API key is set for the OpenAI-compatible provider.",
                provider=self.name,
                hint="Add one with `autoclip config set-secret openai`.",
            )

        kwargs = {"api_key": key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return AsyncOpenAI(**kwargs, max_retries=0, timeout=60.0)

    def _is_local(self) -> bool:
        return bool(self.base_url) and (
            "localhost" in self.base_url or "127.0.0.1" in self.base_url
        )

    async def _complete(
        self, system: str, user: str, config: DetectionConfig, *, json_mode: bool = True
    ) -> str:
        client = self._client()
        request = {
            "model": self.model,
            "temperature": config.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # Only OpenAI's own endpoint reliably honours this; other vendors 400 on
        # it, so a failed request is retried once without it.
        try:
            response = await client.chat.completions.create(
                **request, **({"response_format": {"type": "json_object"}} if json_mode else {})
            )
        except Exception as exc:
            if _is_unsupported_parameter(exc):
                log.debug("Endpoint rejected response_format; retrying without it.")
                try:
                    response = await client.chat.completions.create(**request)
                except Exception as retry_exc:
                    raise _translate(retry_exc, self.name, self.model) from retry_exc
            else:
                raise _translate(exc, self.name, self.model) from exc

        choices = response.choices or []
        if not choices:
            raise ProviderError("The endpoint returned no choices.", provider=self.name)
        return choices[0].message.content or ""

    async def health_check(self) -> ProviderStatus:
        if not self.api_key and not self._is_local():
            return ProviderStatus(
                name=self.name, available=False, detail="No API key set", models=SUGGESTED_MODELS
            )
        try:
            client = self._client()
            models = await client.models.list()
            names = sorted(m.id for m in models.data)[:50]
        except Exception as exc:
            return ProviderStatus(name=self.name, available=False, detail=str(exc)[:200])
        return ProviderStatus(
            name=self.name,
            available=True,
            detail=self.base_url or "https://api.openai.com/v1",
            models=names or SUGGESTED_MODELS,
        )


def _is_unsupported_parameter(exc: Exception) -> bool:
    lowered = str(exc).lower()
    return "response_format" in lowered or "unsupported" in lowered or "unrecognized" in lowered


def _translate(exc: Exception, provider: str, model: str) -> ProviderError:
    # Do not include upstream exception text: it can contain credentials or URLs.
    lowered = str(exc).lower()
    status = getattr(exc, "status_code", None)
    if status in (401, 403) or any(
        x in lowered
        for x in (
            "401",
            "403",
            "invalid api key",
            "incorrect api key",
            "authentication",
            "invalid x-api-key",
        )
    ):
        kind = "auth"
    elif any(x in lowered for x in ("quota", "billing", "credit", "insufficient_quota")):
        kind = "quota"
    elif status == 429 or "429" in lowered or "rate limit" in lowered:
        kind = "rate_limit"
    elif isinstance(exc, TimeoutError) or any(x in lowered for x in ("timeout", "timed out")):
        kind = "timeout"
    elif isinstance(exc, ConnectionError) or "connect" in lowered:
        kind = "connection"
    elif status == 404 or "404" in lowered or "model_not_found" in lowered:
        kind = "model"
    else:
        kind = "unknown"
    return ProviderError(f"Provider request failed ({kind}).", provider=provider, kind=kind)
