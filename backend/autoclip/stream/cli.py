"""``clip`` command line: ``clip stream <vod> --campaign <name>``.

Also mounted into the main CLI as ``autoclip stream``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="clip",
    help="Clip Studio: turn streamer VODs into reviewed 9:16 clips.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback()
def _root() -> None:
    """Clip Studio commands."""


@app.command("stream")
def stream_cmd(
    vod: str = typer.Argument(..., help="Twitch VOD link/id, or a path to a local video file."),
    campaign: str = typer.Option(
        ..., "--campaign", "-c", help="Campaign name (campaigns/<name>.yaml)."
    ),
    start: str = typer.Option("", "--start", help="Trim start of the VOD, e.g. 1:00:00."),
    end: str = typer.Option("", "--end", help="Trim end of the VOD, e.g. 1:30:00."),
    chat: Path | None = typer.Option(
        None, "--chat", help="TwitchDownloader chat JSON for a local video file."
    ),
    quality: str = typer.Option("720p60", "--quality", help="Twitch download quality."),
    highlights_file: Path | None = typer.Option(
        None, "--highlights", help="Use this highlights.json (written by the /clip skill)."
    ),
    prepare_only: bool = typer.Option(
        False, "--prepare-only", help="Stop after writing candidates.json."
    ),
) -> None:
    """Turn one VOD into reviewed vertical clips for a campaign.

    Phase 1 downloads the VOD and chat, transcribes, scores chat hype and writes
    candidates.json. Phase 2 renders the clips Claude picked (highlights.json, written
    by the /clip skill). Run again after the skill finishes; finished work is reused.
    """
    from ..config import load as load_settings
    from ..db import init as db_init
    from . import ingest, pipeline
    from .campaigns import load_campaign

    local = Path(vod).exists()
    if local and (start or end):
        console.print(
            "[red]--start/--end only trim Twitch downloads.[/red] A local file is used as it is: "
            "trim it first (e.g. with ffmpeg) so the chat times still line up."
        )
        raise typer.Exit(2)

    db_init()
    try:
        camp = load_campaign(campaign)
    except Exception as exc:
        console.print(f"[red]Campaign problem:[/red] {exc}")
        raise typer.Exit(2) from exc

    # -- ingest ------------------------------------------------------------
    try:
        with console.status("[cyan]Fetching VOD and chat...", spinner="dots"):
            if ingest.twitch_vod_id(vod) and not local:
                stream = ingest.ingest_twitch_vod(
                    vod, start=start or None, end=end or None, quality=quality
                )
            else:
                stream = ingest.ingest_local(Path(vod), chat_json=chat)
    except ingest.StreamIngestError as exc:
        console.print(f"[red]Ingest failed.[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(
        f"[green]Stream:[/green] {stream.streamer or '?'} / {stream.vod_id} "
        f"({stream.duration_s / 60:.0f} min, chat: {'yes' if stream.chat_path else 'NO'})"
    )

    # -- phase 1 -----------------------------------------------------------
    try:
        prepared = pipeline.prepare(
            stream,
            camp,
            settings=load_settings(),
            on_status=lambda msg: console.print(f"[cyan]>[/cyan] {msg}"),
        )
    except pipeline.StreamPipelineError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[green]Candidates:[/green] {prepared.candidates_path}")
    if highlights_file is not None:
        prepared.highlights_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(highlights_file, prepared.highlights_path)
    if prepare_only or not prepared.highlights_path.exists():
        console.print(
            "\n[yellow]Waiting for clip selection.[/yellow] In Claude Code run "
            f"[bold]/clip {prepared.job.id}[/bold] — it reads candidates.json, writes "
            f"[cyan]{prepared.highlights_path}[/cyan], then re-runs this command.\n"
            f"(Job id: {prepared.job.id})"
        )
        raise typer.Exit(0)

    # -- phase 2 -----------------------------------------------------------
    try:
        outcomes = pipeline.render(
            prepared,
            camp,
            stream=stream,
            on_status=lambda msg: console.print(f"[cyan]>[/cyan] {msg}"),
        )
    except pipeline.StreamPipelineError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    table = Table(title=f"{len(outcomes)} picks", header_style="bold", title_justify="left")
    for col in ("#", "Status", "QA", "Layout", "Spoiler", "Title"):
        table.add_column(col)
    colours = {"exported": "green", "blocked": "red", "rejected": "yellow", "failed": "red"}
    for o in outcomes:
        c = colours.get(o.status, "white")
        table.add_row(
            str(o.rank or "-"),
            f"[{c}]{o.status}[/{c}]",
            str(o.qa_score),
            o.layout_used,
            o.spoiler_level,
            o.title[:60],
        )
    console.print(table)
    exported = [o for o in outcomes if o.status == "exported"]
    console.print(
        f"\n[green]{len(exported)} clips exported[/green]. Report + files: "
        f"{Path(exported[0].path).parent if exported else '-'}\n"
        "Review them with: [cyan]autoclip serve[/cyan]"
    )


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
