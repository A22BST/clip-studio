"""``clip-auto``: the automation commands (also ``python -m autoclip.auto.cli``)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from . import secrets
from .config import load_config
from .store import Store

app = typer.Typer(name="clip-auto", help="Clip Studio automation layer.", no_args_is_help=True)
console = Console()


@app.callback()
def _main() -> None:
    secrets.harden_logging()  # httpx INFO logs would print the Telegram token URL


def _notifier(config=None):
    """Approval chat (Discord by default) + a one-way Telegram ping when its secrets are set."""
    from .notify import CompositeNotifier, RecordingNotifier, TelegramNotifier

    config = config or load_config()
    telegram_ready = secrets.secret_is_set(secrets.TELEGRAM_BOT_TOKEN) and secrets.secret_is_set(
        secrets.TELEGRAM_CHAT_ID
    )
    primary = None
    if config.chat == "discord":
        if secrets.secret_is_set(secrets.DISCORD_BOT_TOKEN) and secrets.secret_is_set(
            secrets.DISCORD_CHANNEL_ID
        ):
            from .discord_notify import DiscordNotifier

            primary = DiscordNotifier()
    elif telegram_ready:
        return TelegramNotifier()  # Telegram is already the approval chat
    if primary is None:
        if telegram_ready:
            return TelegramNotifier()  # only Telegram is configured: use it for everything
        console.print(f"[yellow]{config.chat} secrets not set: messages are dropped.[/yellow]")
        return RecordingNotifier()
    return CompositeNotifier(primary, TelegramNotifier()) if telegram_ready else primary


def _client(config):
    from .uploadpost import UploadPostClient

    if not secrets.secret_is_set(secrets.UPLOAD_POST_API_KEY):
        return None
    return UploadPostClient(None, config.upload_post.base_url, config.upload_post.profile)


@app.command("tiktok-login")
def tiktok_login() -> None:
    """Open TikTok's consent screen; save tokens only after approval."""
    from .tiktok import TikTokError, login

    try:
        # Same hidden-input method as config set-secret; no credential in argv/history.
        for name in (secrets.TIKTOK_CLIENT_KEY, secrets.TIKTOK_CLIENT_SECRET):
            if not secrets.secret_is_set(name):
                value = typer.prompt(f"Value for {name}", hide_input=True).strip()
                if not value:
                    raise TikTokError("Empty credential; nothing authorized")
                secrets.set_secret(name, value)
        console.print("Approve in your browser to connect TikTok. No clip is uploaded by login.")
        login(mode=load_config().tiktok.mode)
    except (TikTokError, secrets.MissingSecretError, RuntimeError, OSError):
        console.print("TikTok login failed or was denied. Check app settings and retry.")
        raise typer.Exit(1) from None
    console.print("TikTok connected. Tokens saved in Windows User environment.")


@app.command("tiktok-status")
def tiktok_status() -> None:
    """Read-only credential presence and creator-info check; never refresh or save tokens."""
    from .tiktok import TikTokError, TikTokPublisher

    for name in (secrets.TIKTOK_CLIENT_KEY, secrets.TIKTOK_CLIENT_SECRET,
                 secrets.TIKTOK_ACCESS_TOKEN, secrets.TIKTOK_REFRESH_TOKEN):
        console.print(f"{name}: {'present' if secrets.secret_is_set(name) else 'missing'}")
    try:
        info = TikTokPublisher().creator_info(refresh=False)
    except (TikTokError, secrets.MissingSecretError):
        console.print(
            "Creator query unavailable: inbox-only grants lack video.publish; "
            "expired tokens need login/refresh."
        )
        raise typer.Exit(1) from None
    # Do not echo untrusted API strings or avatar URLs (which may carry signed tokens).
    console.print("Creator query succeeded.")
    console.print(f"SELF_ONLY available: {'SELF_ONLY' in info.get('privacy_level_options', [])}")


@app.command()
def tick(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Do everything except the upload; send 'WOULD POST' pings instead (first live test).",
    ),
) -> None:
    """Watch for VODs, run queued jobs, send previews, post due clips (Task Scheduler, 30 min)."""
    from . import tick as tick_mod

    config, store = load_config(), Store()
    with tick_mod.TickLock() as lock:
        if not lock.held:
            console.print("Another tick is running: exiting.")
            raise typer.Exit(0)
        client = None if dry_run else _client(config)
        summary = tick_mod.tick(store, config, _notifier(config), client=client, dry_run=dry_run)
    console.print(summary)


@app.command("init-config")
def init_config_cmd(force: bool = typer.Option(False, "--force", help="Overwrite.")) -> None:
    """Write ~/.autoclip/auto/config.yaml from docs/auto-config.example.yaml (fully automatic mode)."""
    from .config import init_config

    try:
        target = init_config(force=force)
    except FileExistsError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(1) from None
    console.print(f"Wrote {target}")


@app.command("outbox")
def outbox_cmd() -> None:
    """Show today's copied count and the local outbox index."""
    from .outbox import outbox_dir, today_count

    config = load_config()
    console.print(f"Today's copied clips: {today_count(config)}")
    console.print(str(outbox_dir(config) / "INDEX.md"))


@app.command()
def bot() -> None:
    """Run the approval bot (long-running; Discord by default). It also posts due clips."""
    from . import runner
    from . import tick as tick_mod

    secrets.harden_logging()
    config, store = load_config(), Store()
    notifier = _notifier(config)

    def cycle(s: Store) -> None:
        tick_mod.post_cycle(s, config, notifier, _client(config))

    def rerender(clip, new_hook):
        return runner.rerender_clip(store, clip, new_hook)

    if config.chat == "discord":
        from . import discord_bot

        discord_bot.run_bot(store, config, notifier=notifier, rerender=rerender, extra_jobs=[cycle])
    else:
        from . import telegram_bot

        telegram_bot.run_bot(store, config, rerender=rerender, extra_jobs=[cycle])


@app.command("post-due")
def post_due(
    dry_run: bool = typer.Option(False, "--dry-run", help="No upload; 'WOULD POST' pings only."),
) -> None:
    """Run only the posting half (previews, scheduling, due posts, reminders)."""
    from . import tick as tick_mod

    config = load_config()
    client = None if dry_run else _client(config)
    console.print(
        tick_mod.post_cycle(Store(), config, _notifier(config), client, dry_run=dry_run)
    )


@app.command()
def track() -> None:
    """Pull views for posted clips and rewrite the tracker CSV (daily)."""
    from . import tracker

    config = load_config()
    client = _client(config)
    if client is None:
        console.print("[red]UPLOAD_POST_API_KEY is not set.[/red]")
        raise typer.Exit(1)
    store = Store()
    tracker.pull_views(store, config, client)
    from . import throttle

    for platform in throttle.evaluate(store, config):
        console.print(f"[yellow]Throttled {platform}: paused 48 h, cap halved.[/yellow]")
        _notifier(config).send_text(
            f"Auto-throttle: {platform} paused for 48 h and its daily cap halved "
            "(its last 3 posts average under 20% of the 7-day average)."
        )
    console.print(f"Tracker: {config.tracker_csv()}")


@app.command()
def weekly() -> None:
    """Weekly learn-and-report job (what-works file + Telegram report)."""
    from . import learn

    config = load_config()
    console.print(learn.run_weekly(Store(), config, _notifier(config)))


@app.command()
def status() -> None:
    """Show queue, pause state and recent events (no secrets)."""
    from . import approval

    config = load_config()
    console.print(approval.status_text(Store(), config))
    info = {
        "mode": config.mode_text(),
        "chat_backend": config.chat,
        "telegram_token": secrets.secret_is_set(secrets.TELEGRAM_BOT_TOKEN),
        "telegram_chat": secrets.secret_is_set(secrets.TELEGRAM_CHAT_ID),
        "upload_post_key": secrets.secret_is_set(secrets.UPLOAD_POST_API_KEY),
        "twitch": secrets.secret_is_set(secrets.TWITCH_CLIENT_ID),
        "level2_active": config.level2_active,
        "manual_platforms": config.upload_post.manual_platforms,
    }
    if config.chat == "discord":  # legacy backend, kept but not part of the default path
        info |= {
            "discord_token": secrets.secret_is_set(secrets.DISCORD_BOT_TOKEN),
            "discord_channel": secrets.secret_is_set(secrets.DISCORD_CHANNEL_ID),
            "discord_owner": secrets.secret_is_set(secrets.DISCORD_OWNER_ID),
        }
    console.print(info)


@app.command("report-removal")
def report_removal(platform: str, reason: str = "removed / strike / copyright claim") -> None:
    """A post was removed or got a strike: pause EVERYTHING until `clip-auto resume`."""
    from . import throttle

    throttle.report_removal(Store(), platform, reason)
    _notifier().send_text(f"EVERYTHING PAUSED: {platform} reported a removal/strike ({reason}). Run `clip-auto resume` after checking.")
    console.print("Everything is paused. Run `clip-auto resume` after you have looked at it.")


@app.command()
def pause() -> None:
    """Kill switch (same as /pause in Telegram)."""
    Store().set_paused(True, "cli")
    _notifier().send_text("Paused from the command line: nothing posts until `clip-auto resume`.")
    console.print("Paused: nothing will post and no new jobs start.")


@app.command()
def resume() -> None:
    Store().set_paused(False, "cli")
    console.print("Resumed.")


@app.command()
def enqueue(vod: str, campaign: str, start: float = 0, end: float = 0) -> None:
    """Queue a VOD by hand (campaign = file stem with an automation sidecar)."""
    from .campaign_meta import load_auto_campaign

    load_auto_campaign(campaign)  # raises when unknown / not automated
    from ..stream.ingest import twitch_vod_id

    vod_id = twitch_vod_id(vod) or vod
    job = Store().add_job(
        campaign_key=campaign, platform="twitch", vod_id=vod_id, url=vod, start_s=start, end_s=end
    )
    console.print(f"Queued job {job}" if job else "Already queued.")


@app.command("install-tasks")
def install_tasks(
    apply: bool = typer.Option(False, "--apply", help="Really create the scheduled tasks."),
    uninstall: bool = typer.Option(False, "--uninstall"),
    python_exe: Path | None = typer.Option(None, help="Python of the checkout to run."),
    repo_dir: Path | None = typer.Option(None, help="Checkout directory (default: this one)."),
) -> None:
    """Create the Windows Task Scheduler entries. Dry run unless --apply."""
    from . import winsched

    if uninstall:
        winsched.uninstall_tasks(dry_run=not apply)
        return
    plans = winsched.install_tasks(
        dry_run=not apply, python_exe=python_exe or None, repo_dir=repo_dir or None
    )
    for plan in plans:
        console.print(f"{plan['name']}: {' '.join(plan['command'])}")
    console.print("[green]Created.[/green]" if apply else "Dry run only. Add --apply to create.")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
