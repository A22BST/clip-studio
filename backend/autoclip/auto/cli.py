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


@app.command()
def tick() -> None:
    """Watch for VODs, run queued jobs, send previews, post due clips (Task Scheduler, 30 min)."""
    from . import tick as tick_mod

    config, store = load_config(), Store()
    with tick_mod.TickLock() as lock:
        if not lock.held:
            console.print("Another tick is running: exiting.")
            raise typer.Exit(0)
        summary = tick_mod.tick(store, config, _notifier(config), client=_client(config))
    console.print(summary)


@app.command()
def bot() -> None:
    """Run the approval bot (long-running; Discord by default). It also posts due clips."""
    from . import runner
    from . import tick as tick_mod

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
def post_due() -> None:
    """Run only the posting half (previews, scheduling, due posts, reminders)."""
    from . import tick as tick_mod

    config = load_config()
    console.print(tick_mod.post_cycle(Store(), config, _notifier(config), _client(config)))


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
    console.print(
        {
            "telegram_token": secrets.secret_is_set(secrets.TELEGRAM_BOT_TOKEN),
            "telegram_chat": secrets.secret_is_set(secrets.TELEGRAM_CHAT_ID),
            "discord_token": secrets.secret_is_set(secrets.DISCORD_BOT_TOKEN),
            "discord_channel": secrets.secret_is_set(secrets.DISCORD_CHANNEL_ID),
            "discord_owner": secrets.secret_is_set(secrets.DISCORD_OWNER_ID),
            "chat_backend": config.chat,
            "upload_post_key": secrets.secret_is_set(secrets.UPLOAD_POST_API_KEY),
            "twitch": secrets.secret_is_set(secrets.TWITCH_CLIENT_ID),
            "level2_active": config.level2_active,
        }
    )


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
