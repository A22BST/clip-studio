"""Shared fixtures for the automation tests: isolated root, a test campaign, an approved clip."""

from __future__ import annotations

import pytest
from autoclip.auto import gate
from autoclip.auto.config import AutoConfig
from autoclip.auto.store import Store

CAMPAIGN_YAML = """\
name: Test Campaign
platforms: [tiktok, youtube, instagram]
min_duration_s: 5
max_duration_s: 90
required_hashtags: [GTA6]
rate_per_1k_usd: 1.0
"""
SIDECAR_YAML = "streamers: [teststreamer]\nactive: true\nsubmit_url: https://example.test/submit\n"
CHAT = "123"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path / "home"))
    camp = tmp_path / "campaigns"
    (camp / "auto").mkdir(parents=True)
    (camp / "test-campaign.yaml").write_text(CAMPAIGN_YAML, encoding="utf-8")
    (camp / "auto" / "test-campaign.yaml").write_text(SIDECAR_YAML, encoding="utf-8")
    monkeypatch.setenv("CLIPSTUDIO_CAMPAIGNS_DIR", str(camp))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("UPLOAD_POST_API_KEY", "fake-key")
    store = Store(tmp_path / "auto.db")
    return type("Env", (), {"store": store, "tmp": tmp_path, "campaigns": camp, "config": AutoConfig()})


@pytest.fixture
def make_clip(env):
    """Create a clip row (pending_approval) backed by a real small file."""

    def _make(*, approve: bool = False, qa: int = 80, **overrides):
        job_id = env.store.add_job(
            campaign_key="test-campaign", vod_id=f"v{len(env.store.list_jobs())}", start_s=0, end_s=0
        )
        n = len(env.store.list_clips())
        path = env.tmp / f"clip{n}.mp4"
        path.write_bytes(b"fake mp4 bytes %d" % n)
        fields = dict(
            job_id=job_id, campaign_key="test-campaign", title="He did NOT expect this",
            hook="Wait for it", caption="Insane moment", hashtags=["GTA6", "KreekCraft"],
            qa_score=qa, spoiler_level="none", layout="facecam", path=str(path),
            duration_s=30.0, report_status="exported", status="pending_approval",
        )  # fmt: skip
        fields.update(overrides)
        clip_id = env.store.add_clip(**fields)
        if approve:
            sha = gate.sha256_file(path)
            env.store.mark_previewed(clip_id, sha, 1)
            env.store.approve_clip(clip_id, f"telegram:{CHAT}", sha)
        return clip_id

    return _make


GATE_KW = {"probe_duration": lambda _p: 30.0}
