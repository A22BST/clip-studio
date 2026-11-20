"""Discord approval bot (default backend), connected outward through the gateway.

* Buttons on each clip message: Approve / Reject / Edit hook (opens a modal) and, on posted
  messages, "Submitted" for the campaign-submission reminder. Button ids are the same strings
  the Telegram bot uses (``a:<id>``, ``r:<id>``, ``e:<id>``, ``s:<post_id>``).
* Slash commands: /pause /resume /status.
* EVERY interaction is checked against ``DISCORD_OWNER_ID`` (and the configured channel) before
  anything happens; anyone else gets an ephemeral "not allowed" and nothing changes.
* A 60 s loop sends new previews and runs the post cycle, like the Telegram bot.

The bot token is read from the environment and never printed or stored.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from . import approval, secrets
from .config import AutoConfig, load_config
from .store import Store

log = logging.getLogger(__name__)


def authorized(user_id: int | str | None, channel_id: int | str | None, owner: str, channel: str) -> bool:
    """Only the owner, only in the configured channel (or DMs are rejected)."""
    return (
        user_id is not None
        and channel_id is not None
        and str(user_id) == str(owner)
        and str(channel_id) == str(channel)
    )


def handle_button(
    store: Store, config: AutoConfig, custom_id: str, owner_id: str
) -> tuple[str, str | None]:
    """Pure button logic: returns (reply text, follow-up) with follow-up 'edit:<clip_id>' for a modal."""
    kind, _, raw = custom_id.partition(":")
    if not raw.isdigit():
        return "Unknown button.", None
    target = int(raw)
    if kind == "a":
        return approval.approve(store, target, int(owner_id), config, source="discord"), None
    if kind == "r":
        return approval.reject(store, target, int(owner_id), source="discord"), None
    if kind == "e":
        message = approval.begin_edit_hook(store, target)
        return message, (f"edit:{target}" if message.startswith("Send") else None)
    if kind == "s":
        store.mark_submitted(target)
        return "Logged as submitted.", None
    return "Unknown button.", None


def build_client(
    store: Store,
    config: AutoConfig,
    *,
    owner_id: str,
    channel_id: str,
    notifier: Any,
    rerender: Callable[[dict[str, Any], str], Any] | None = None,
    extra_jobs: list[Callable[[Store], object]] | None = None,
):
    import discord
    from discord import app_commands
    from discord.ext import tasks

    intents = discord.Intents.none()
    intents.guilds = True
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    def ok(interaction: discord.Interaction) -> bool:
        allowed = authorized(
            interaction.user.id if interaction.user else None, interaction.channel_id, owner_id, channel_id
        )
        if not allowed:
            store.log_event("unauthorized_interaction", "discord")  # no ids or content stored
        return allowed

    async def deny(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Not allowed.", ephemeral=True)

    class HookModal(discord.ui.Modal, title="New hook"):
        hook = discord.ui.TextInput(label="Hook (1-60 chars, one line)", max_length=60)

        def __init__(self, clip_id: int) -> None:
            super().__init__()
            self.clip_id = clip_id

        async def on_submit(self, interaction: discord.Interaction) -> None:
            if not ok(interaction):
                return await deny(interaction)
            if rerender is None:
                store.set_clip_status(self.clip_id, "pending_approval")
                return await interaction.response.send_message("Hook editing is not set up.", ephemeral=True)
            await interaction.response.defer(ephemeral=True, thinking=True)
            text = await asyncio.to_thread(
                approval.apply_hook_edit, store, self.clip_id, str(self.hook), rerender
            )
            await interaction.followup.send(text, ephemeral=True)

    @client.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return  # slash commands and modals are routed by the tree / the modal itself
        if not ok(interaction):
            return await deny(interaction)
        custom_id = (interaction.data or {}).get("custom_id", "")
        reply, follow = handle_button(store, config, custom_id, owner_id)
        if follow and follow.startswith("edit:"):
            return await interaction.response.send_modal(HookModal(int(follow.split(":")[1])))
        try:  # remove the buttons after a decision so a clip cannot be decided twice
            if custom_id[:1] in "ars":
                await interaction.response.edit_message(view=None)
                await interaction.followup.send(reply, ephemeral=True)
            else:
                await interaction.response.send_message(reply, ephemeral=True)
        except discord.HTTPException:
            log.warning("could not answer a button interaction")

    @tree.command(name="pause", description="Stop all posting and new jobs")
    async def pause(interaction: discord.Interaction) -> None:
        if not ok(interaction):
            return await deny(interaction)
        store.set_paused(True, "discord")
        await interaction.response.send_message("Paused. Nothing will post until /resume.")

    @tree.command(name="resume", description="Resume posting")
    async def resume(interaction: discord.Interaction) -> None:
        if not ok(interaction):
            return await deny(interaction)
        store.set_paused(False, "discord")
        await interaction.response.send_message("Resumed.")

    @tree.command(name="status", description="Queue and pause status")
    async def status(interaction: discord.Interaction) -> None:
        if not ok(interaction):
            return await deny(interaction)
        await interaction.response.send_message(approval.status_text(store, config)[:1900], ephemeral=True)

    @tasks.loop(seconds=60)
    async def cycle() -> None:
        try:
            await asyncio.to_thread(approval.send_pending_previews, store, notifier, config)
            for job in extra_jobs or []:
                await asyncio.to_thread(job, store)
        except Exception as exc:  # the loop must survive any single failure
            store.log_event("cycle_error", f"{type(exc).__name__}: {str(exc)[:200]}")

    @client.event
    async def on_ready() -> None:
        if not cycle.is_running():
            cycle.start()
        guild_ids = [g.id for g in client.guilds]
        for gid in guild_ids:  # guild-scoped sync appears instantly
            tree.copy_global_to(guild=discord.Object(gid))
            await tree.sync(guild=discord.Object(gid))

    client.cycle_task = cycle  # exposed for tests
    return client


def run_bot(
    store: Store | None = None,
    config: AutoConfig | None = None,
    *,
    notifier: Any = None,
    rerender: Callable[[dict[str, Any], str], Any] | None = None,
    extra_jobs: list[Callable[[Store], object]] | None = None,
) -> None:
    from .discord_notify import DiscordNotifier

    token = secrets.require_secret(secrets.DISCORD_BOT_TOKEN)
    owner = secrets.require_secret(secrets.DISCORD_OWNER_ID)
    channel = secrets.require_secret(secrets.DISCORD_CHANNEL_ID)
    client = build_client(
        store or Store(),
        config or load_config(),
        owner_id=owner,
        channel_id=channel,
        notifier=notifier or DiscordNotifier(),
        rerender=rerender,
        extra_jobs=extra_jobs,
    )
    client.run(token, log_handler=None)
