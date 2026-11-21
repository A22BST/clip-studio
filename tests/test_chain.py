"""All provider calls and credential access are fake; no external services."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from autoclip.config import Settings
from autoclip.providers import chain
from autoclip.providers.base import DetectionConfig, ProviderError
from autoclip.providers.openai_provider import OpenAIProvider, _translate


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    chain._COOLDOWNS.clear()
    monkeypatch.setattr(chain, "get_secret", lambda *args: "fake")
    yield
    chain._COOLDOWNS.clear()


def settings(**kwargs):
    return Settings(
        chain={
            "entries": [
                {
                    "name": "first",
                    "model": "a",
                    "key_name": "first-key",
                    "base_url": "https://first.invalid/v1",
                },
                {
                    "name": "second",
                    "model": "b",
                    "key_name": "second-key",
                    "base_url": "https://second.invalid/v1",
                },
            ],
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    "error,kind",
    [
        ("429", "rate_limit"),
        ("429 insufficient_quota", "quota"),
        ("Connection error", "connection"),
        ("Request timed out", "timeout"),
        ("401", "auth"),
        ("403", "auth"),
    ],
)
def test_fallback(monkeypatch, caplog, error, kind):
    seen = []

    async def complete(self, *args, **kwargs):
        seen.append(self.model)
        if self.model == "a":
            raise _translate(Exception(error), "openai", self.model)
        return "answer"

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    assert _translate(Exception(error), "openai", "a").kind == kind
    text, result = chain.ChainProvider(settings()).complete_text("s", "u")
    assert text == "answer" and result == chain.ChainResult("second", "b")
    assert seen == ["a", "b"]
    if kind == "auth":
        assert "first" in caplog.text and "first-key" in caplog.text
        assert "fake" not in caplog.text


def test_missing_key_skipped(monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr(
        chain, "get_secret", lambda name, *a: None if name == "first-key" else "fake"
    )
    complete = AsyncMock(return_value="ok")
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    assert chain.ChainProvider(settings()).complete_text("s", "u")[1].provider == "second"
    assert complete.call_count == 1 and "first-key" in caplog.text


def test_bad_json_falls_through_with_feedback(monkeypatch):
    seen = []

    async def complete(self, system, user, *args, **kwargs):
        seen.append((self.model, user))
        return "bad" if self.model == "a" else '{"ok": true}'

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    _, result = chain.ChainProvider(settings()).complete_validated("s", "u", json.loads)
    assert result.provider == "second"
    assert [m for m, _ in seen] == ["a", "a", "b"]
    assert "previous response was invalid" in seen[1][1]


def test_cooldown_shared_across_instances_and_expires(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(chain.time, "monotonic", lambda: clock[0])
    seen = []

    async def complete(self, *args, **kwargs):
        seen.append(self.model)
        if self.model == "a":
            raise ProviderError("rate", kind="rate_limit")
        return "ok"

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    for _ in range(2):
        chain.ChainProvider(settings()).complete_text("s", "u")
    assert seen == ["a", "b", "b"]
    clock[0] = 71
    chain.ChainProvider(settings()).complete_text("s", "u")
    assert seen[-2:] == ["a", "b"]


@pytest.mark.parametrize("allow", [False, True])
def test_claude_requires_opt_in_and_is_last(monkeypatch, allow):
    conf = settings(allow_claude=allow)
    complete = AsyncMock(return_value="claude text")
    monkeypatch.setattr(chain.AnthropicProvider, "_complete", complete)
    monkeypatch.setattr(
        chain, "get_secret", lambda name, *a: "fake" if name == "anthropic" else None
    )
    provider = chain.ChainProvider(conf)
    if allow:
        assert provider.complete_text("s", "u")[1].provider == "anthropic"
        assert complete.call_args.kwargs == {"json_mode": False}
    else:
        with pytest.raises(ProviderError):
            provider.complete_text("s", "u")
        complete.assert_not_called()


def test_explicit_claude_entry_disabled_even_over_openai(monkeypatch):
    conf = Settings(
        chain={
            "entries": [
                {
                    "name": "custom",
                    "model": "anthropic/claude-free",
                    "base_url": "https://custom.invalid/v1",
                }
            ]
        }
    )
    complete = AsyncMock()
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    with pytest.raises(ProviderError):
        chain.ChainProvider(conf).complete_text("s", "u")
    complete.assert_not_called()


async def test_plain_chat_has_no_tools_or_json_format(monkeypatch):
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="report"))]
        )
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(OpenAIProvider, "_client", lambda self: client)
    provider = OpenAIProvider("test", api_key="fake")
    assert await provider._complete("s", "u", DetectionConfig(), json_mode=False) == "report"
    assert set(create.call_args.kwargs) == {"model", "temperature", "messages"}


def test_unknown_error_is_not_silently_masked(monkeypatch):
    monkeypatch.setattr(OpenAIProvider, "_complete", AsyncMock(side_effect=ProviderError("bad")))
    with pytest.raises(ProviderError, match="bad"):
        chain.ChainProvider(settings()).complete_text("s", "u")


def test_presets_verified_and_defaults_order():
    from autoclip.providers.presets import PRESETS

    provider = chain.ChainProvider(Settings())
    assert [e.name for e in provider.entries] == list(PRESETS)
    assert all(p["verified"] is True and p["checked"] == "2026-11-21" for p in PRESETS.values())


def test_missing_endpoint_or_model_fails_before_network():
    with pytest.raises(ProviderError, match="needs a base_url and model"):
        chain.ChainProvider(Settings(chain={"entries": [{"name": "incomplete"}]}))


def test_entry_overrides_preset():
    entry = chain.resolve_entry(
        chain.ChainEntry(
            name="custom",
            preset="groq",
            model="override",
            key_name="custom-key",
            base_url="https://custom.invalid/v1",
        )
    )
    assert entry.model == "override" and entry.key_name == "custom-key"
    assert entry.base_url == "https://custom.invalid/v1"


def test_malformed_attempt_limit_configurable(monkeypatch):
    replies = iter(["bad", "bad", "bad", '{"ok":true}'])
    complete = AsyncMock(side_effect=lambda *a, **k: next(replies))
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    provider = chain.ChainProvider(settings(malformed_attempts=3))
    assert provider.complete_validated("s", "u", json.loads)[1].provider == "second"
    assert complete.call_count == 4


def test_all_missing_keys_raise_without_network(monkeypatch):
    monkeypatch.setattr(chain, "get_secret", lambda *a: None)
    complete = AsyncMock()
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    with pytest.raises(ProviderError, match="No usable"):
        chain.ChainProvider(settings()).complete_text("s", "u")
    complete.assert_not_called()


def test_caller_attempt_limit_advances_after_one_bad_reply(monkeypatch):
    complete = AsyncMock(side_effect=["bad", '{"ok":true}'])
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    provider = chain.ChainProvider(settings())
    assert provider.complete_validated("s", "u", json.loads, max_attempts=1)[1].provider == "second"
    assert complete.call_count == 2


def test_default_chain_secrets_supported_by_existing_cli():
    from autoclip.config import KEYED_PROVIDERS

    assert all(
        e.key_name in KEYED_PROVIDERS
        for e in chain.ChainProvider(Settings()).entries
        if e.name != "ollama"
    )
    assert "cloudflare-account-id" in KEYED_PROVIDERS


def bucket_settings(**entry_overrides):
    conf = settings()
    conf.chain.entries[0] = chain.ChainEntry(
        name="first",
        base_url="https://first.invalid/v1",
        key_name="first-key",
        models=["heavy", "small"],
        **entry_overrides,
    )
    return conf


@pytest.mark.parametrize("kind", ["model", "malformed", "empty"])
def test_model_failure_stays_in_bucket(monkeypatch, kind):
    seen = []

    async def complete(self, *a, **k):
        seen.append(self.model)
        if self.model == "heavy":
            if kind == "empty":
                return ""
            raise ProviderError("bad model", kind=kind)
        return "ok"

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    provider = chain.ChainProvider(bucket_settings())
    assert provider.complete_text("s", "u")[1] == chain.ChainResult("first", "small")
    assert seen == ["heavy", "small"]
    assert chain.usage(provider.entries[0])["used"] == 2


def test_malformed_validation_uses_next_model(monkeypatch):
    seen = []

    async def complete(self, *a, **k):
        seen.append(self.model)
        return "bad" if self.model == "heavy" else '{"ok":true}'

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    provider = chain.ChainProvider(bucket_settings())
    assert provider.complete_validated("s", "u", json.loads)[1].model == "small"
    assert seen == ["heavy", "heavy", "small"]


@pytest.mark.parametrize("kind", ["rate_limit", "quota", "auth", "connection", "timeout"])
def test_account_failure_skips_remaining_models(monkeypatch, kind):
    seen = []

    async def complete(self, *a, **k):
        seen.append(self.model)
        if self.model == "heavy":
            raise ProviderError("account failure", kind=kind)
        return "ok"

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    provider = chain.ChainProvider(bucket_settings())
    assert provider.complete_text("s", "u")[1].provider == "second"
    assert seen == ["heavy", "b"]
    assert chain.usage(provider.entries[0])["used"] == 1


@pytest.mark.parametrize(
    "reset,cutoff",
    [
        ("utc", "2026-11-22T00:00:00+00:00"),
        ("America/Los_Angeles", "2026-11-22T08:00:00+00:00"),
    ],
)
def test_daily_budget_persisted_and_resets(monkeypatch, reset, cutoff, autoclip_home):
    from datetime import datetime

    clock = [datetime.fromisoformat(cutoff).timestamp() - 1]
    monkeypatch.setattr(chain.time, "time", lambda: clock[0])
    complete = AsyncMock(return_value="ok")
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    conf = bucket_settings(daily_requests=1, reset=reset)
    first = chain.ChainProvider(conf)
    second = chain.ChainProvider(conf)
    assert first.complete_text("s", "u")[1].provider == "first"
    assert second.complete_text("s", "u")[1].provider == "second"
    assert chain.usage(second.entries[0])["used"] == 1
    assert (autoclip_home / "auto" / "chain-usage.json").is_file()
    clock[0] += 1
    assert second.complete_text("s", "u")[1].provider == "first"
    assert chain.usage(second.entries[0])["used"] == 1


@pytest.mark.parametrize("daily", [True, False])
def test_quota_spent_only_for_daily_failure(monkeypatch, daily):
    clock = [10.0]
    monkeypatch.setattr(chain.time, "monotonic", lambda: clock[0])
    seen = []

    async def complete(self, *a, **k):
        seen.append(self.model)
        if self.model == "heavy":
            # Match the adapter's translated error with the original as cause.
            cause = Exception("429 daily requests limit" if daily else "429 tokens per minute")
            raise ProviderError("rate", kind="rate_limit") from cause
        return "ok"

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    conf = bucket_settings()
    provider = chain.ChainProvider(conf)
    provider.complete_text("s", "u")
    assert chain.usage(provider.entries[0])["spent"] is daily
    clock[0] += 61
    chain.ChainProvider(conf).complete_text("s", "u")
    assert seen == (["heavy", "b", "b"] if daily else ["heavy", "b", "heavy", "b"])


def test_failed_model_call_spends_last_daily_request(monkeypatch):
    complete = AsyncMock(side_effect=[ProviderError("gone", kind="model"), "fallback"])
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    provider = chain.ChainProvider(bucket_settings(daily_requests=1))
    assert provider.complete_text("s", "u")[1].provider == "second"
    assert complete.call_count == 2
    assert chain.usage(provider.entries[0])["used"] == 1


def test_prompt_guard_skips_without_spending(monkeypatch):
    complete = AsyncMock(return_value="ok")
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    provider = chain.ChainProvider(bucket_settings(max_prompt_tokens=2))
    assert provider.complete_text("1234", "12345")[1].provider == "second"
    assert chain.usage(provider.entries[0])["used"] == 0
    assert complete.call_count == 1


@pytest.mark.parametrize("account", [None, "account-123"])
def test_cloudflare_account_substitution(monkeypatch, caplog, account):
    caplog.set_level("INFO")
    monkeypatch.setattr(
        chain, "get_secret", lambda name, *a: account if name == "cloudflare-account-id" else "fake"
    )
    conf = settings()
    conf.chain.entries[0] = chain.ChainEntry(name="cf", preset="cloudflare-workers-ai")
    seen = []

    async def complete(self, *a, **k):
        seen.append(self.base_url)
        return "ok"

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    result = chain.ChainProvider(conf).complete_text("s", "u")[1]
    if account:
        assert result.provider == "cf"
        assert seen == ["https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1"]
    else:
        assert result.provider == "second"
        assert "cloudflare-account-id" in caplog.text
    assert "fake" not in caplog.text


@pytest.mark.parametrize("idle", [False, True])
def test_local_order_and_idle_gate(monkeypatch, idle):
    conf = settings(allow_claude=True)
    conf.chain.entries.insert(0, chain.ChainEntry(name="ollama", models=["local"]))
    monkeypatch.setattr(chain, "gpu_idle", lambda: idle)
    monkeypatch.setattr(
        chain, "get_secret", lambda name, *a: "fake" if name == "anthropic" else None
    )
    local = AsyncMock(return_value="local answer")
    claude = AsyncMock(return_value="claude answer")
    monkeypatch.setattr(chain.OllamaProvider, "_complete", local)
    monkeypatch.setattr(chain.AnthropicProvider, "_complete", claude)
    provider = chain.ChainProvider(conf)
    assert [e.name for e in provider.entries] == ["first", "second", "ollama", "anthropic"]
    assert provider.complete_text("s", "u")[1].provider == ("ollama" if idle else "anthropic")
    assert local.call_count == int(idle)
    if idle:
        assert local.call_args.kwargs == {}


def test_gpu_state_unknown_busy_and_idle(autoclip_home, initialised_db):
    from autoclip import db

    assert chain.gpu_idle()
    with db.connection() as conn:
        # Real schema ensures the indicator matches existing pipeline state.
        conn.execute(
            "INSERT INTO sources (id, type, filename, path, title, created_at) "
            "VALUES ('s', 'upload', 'f', 'p', 't', '2026-11-21')"
        )
        conn.execute(
            "INSERT INTO jobs "
            "(id, source_id, status, settings_json, created_at, updated_at) "
            "VALUES ('j', 's', 'running', '{}', '2026-11-21', '2026-11-21')"
        )
    assert not chain.gpu_idle()
    with db.connection() as conn:
        conn.execute("UPDATE jobs SET status='done'")
    assert chain.gpu_idle()
    lock = autoclip_home / "auto" / "tick.lock"
    lock.write_text("unknown pid")
    assert not chain.gpu_idle()


def test_gpu_missing_database_is_unknown():
    assert not chain.gpu_idle()


def test_daily_usage_aliases_share_account(monkeypatch):
    conf = bucket_settings(daily_requests=1)
    conf.chain.entries.insert(1, conf.chain.entries[0].model_copy(update={"name": "alias"}))
    monkeypatch.setattr(OpenAIProvider, "_complete", AsyncMock(return_value="ok"))
    provider = chain.ChainProvider(conf)
    provider.complete_text("s", "u")
    assert provider.complete_text("s", "u")[1].provider == "second"


def test_chain_cli_and_cloudflare_secret(monkeypatch):
    from autoclip import cli
    from typer.testing import CliRunner

    monkeypatch.setattr(cli.config, "load", lambda: bucket_settings(daily_requests=1))
    monkeypatch.setattr(cli.config, "get_secret", lambda *a: "NEVER-PRINT-THIS")
    monkeypatch.setattr(OpenAIProvider, "_complete", AsyncMock(return_value="ok"))
    chain.ChainProvider(bucket_settings(daily_requests=1)).complete_text("s", "u")
    result = CliRunner().invoke(cli.app, ["config", "chain"], env={"COLUMNS": "160"})
    assert result.exit_code == 0, result.output
    assert "heavy, small" in result.output and "1 / 1" in result.output
    assert "present" in result.output and "NEVER-PRINT-THIS" not in result.output
    store = []
    monkeypatch.setattr(cli.config, "set_secret", lambda *a: store.append(a) or True)
    result = CliRunner().invoke(
        cli.app, ["config", "set-secret", "cloudflare-account-id"], input="test-account\n"
    )
    assert result.exit_code == 0, result.output
    assert store == [("cloudflare-account-id", "test-account")]


def test_unreadable_usage_fails_closed(monkeypatch, autoclip_home):
    path = autoclip_home / "auto" / "chain-usage.json"
    path.parent.mkdir(parents=True)
    path.write_text("broken JSON")
    complete = AsyncMock()
    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    with pytest.raises(ProviderError, match="daily usage"):
        chain.ChainProvider(settings()).complete_text("s", "u")
    complete.assert_not_called()


def test_reservations_are_atomic_across_processes():
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = """
from autoclip.config import ChainEntry
from autoclip.providers.chain import resolve_entry, usage
entry = resolve_entry(ChainEntry(name='p', preset='groq', daily_requests=10))
print(sum(usage(entry, reserve=True)['allowed'] for _ in range(8)))
"""
    env = {**os.environ, "PYTHONPATH": str(Path("backend").resolve())}
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    counts = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        counts.append(int(stdout.strip()))
    assert sum(counts) == 10
    entry = chain.resolve_entry(chain.ChainEntry(name="p", preset="groq", daily_requests=10))
    assert chain.usage(entry)["used"] == 10


def test_daily_spent_marker_expires_even_without_known_budget(monkeypatch):
    from datetime import datetime

    clock = [datetime.fromisoformat("2026-11-21T23:59:59+00:00").timestamp()]
    monkeypatch.setattr(chain.time, "time", lambda: clock[0])
    entry = chain.ChainProvider(bucket_settings()).entries[0]
    chain.usage(entry, spent=True)
    assert not chain.usage(entry, reserve=True)["allowed"]
    clock[0] += 1
    assert chain.usage(entry, reserve=True)["allowed"]
    assert chain.usage(entry)["used"] == 1


def test_model_404_translation_and_empty_choices_fallback(monkeypatch):
    seen = []

    async def complete(self, *a, **k):
        seen.append(self.model)
        if self.model == "heavy":
            raise _translate(Exception("404 model gone"), "openai", self.model)
        if self.model == "small":
            raise ProviderError("The endpoint returned no choices.", provider="openai")
        return "ok"

    monkeypatch.setattr(OpenAIProvider, "_complete", complete)
    provider = chain.ChainProvider(bucket_settings())
    assert provider.complete_text("s", "u")[1].provider == "second"
    assert seen == ["heavy", "small", "b"]


@pytest.mark.parametrize("budget", [1, 2])
def test_adapter_retry_counts_each_http_attempt(monkeypatch, budget):
    creates = {}

    def client(self):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
        create = AsyncMock(
            side_effect=[Exception("unsupported parameter"), response]
            if self.model == "heavy"
            else [response]
        )
        creates[self.model] = create
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(OpenAIProvider, "_client", client)
    provider = chain.ChainProvider(bucket_settings(daily_requests=budget))
    result = provider.complete_text("s", "u")[1]
    assert result.provider == ("first" if budget == 2 else "second")
    assert creates["heavy"].call_count == budget
    assert chain.usage(provider.entries[0])["used"] == budget


@pytest.mark.parametrize("timeout", [False, True])
def test_local_native_connection_errors_allow_last_claude(monkeypatch, timeout):
    import httpx

    conf = Settings(
        chain={"entries": [{"name": "ollama", "models": ["local"]}], "allow_claude": True}
    )
    monkeypatch.setattr(chain, "gpu_idle", lambda: True)

    async def complete(*args, **kwargs):
        cause = httpx.ReadTimeout("") if timeout else httpx.ConnectError("offline")
        raise ProviderError("Could not reach Ollama.") from cause

    monkeypatch.setattr(chain.OllamaProvider, "_complete", complete)
    monkeypatch.setattr(chain.AnthropicProvider, "_complete", AsyncMock(return_value="ok"))
    assert chain.ChainProvider(conf).complete_text("s", "u")[1].provider == "anthropic"
