"""Stream ingest (step 2a): a Twitch VOD plus its chat replay, stored together.

TwitchDownloaderCLI (MIT, lay295/TwitchDownloader) is used as an external program
and is not vendored. It writes both the video and the chat JSON, and chat times are
seconds from the start of the VOD, which is the same clock as the video file.
When the VOD is downloaded trimmed (``--start``/``--end``), chat is shifted so that
it lines up with the trimmed file. Everything lands in one folder:

    <root>/streams/<vod_id>/
        vod.mp4        the video (trimmed if asked)
        chat_raw.json  TwitchDownloader's own JSON, untouched
        chat.json      our ChatLog (times relative to vod.mp4)
        stream.json    metadata: url, streamer, title, trim, duration

Local files work too (``--chat`` for a chat JSON you already have). A YouTube/Kick
VOD without chat is allowed; hype detection then falls back to audio loudness.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import paths
from ..pipeline import ffmpeg
from .chat import ChatLog, parse_twitchdownloader_json

log = logging.getLogger(__name__)

ENV_CLI = "TWITCHDOWNLOADER_CLI"
DEFAULT_CLI_DIR = Path.home() / "tools" / "TwitchDownloaderCLI"

_TWITCH_VOD = re.compile(r"(?:twitch\.tv/(?:[^/]+/)?videos?/|^)(\d{6,})(?:[/?#]|$)")


class StreamIngestError(RuntimeError):
    """A stream could not be downloaded or stored."""


@dataclass
class StreamSource:
    vod_id: str
    folder: Path
    video: Path
    chat_path: Path | None  # our ChatLog JSON, or None when there is no chat
    streamer: str = ""
    title: str = ""
    url: str = ""
    trim_start_s: float = 0.0
    duration_s: float = 0.0

    def load_chat(self) -> ChatLog | None:
        return ChatLog.load(self.chat_path) if self.chat_path and self.chat_path.exists() else None


def streams_dir() -> Path:
    return paths.root() / "streams"


def twitch_vod_id(url_or_id: str) -> str | None:
    match = _TWITCH_VOD.search(url_or_id.strip())
    return match.group(1) if match else None


def find_cli() -> str:
    """Locate TwitchDownloaderCLI: env var, PATH, then the default tools folder."""
    candidates = [os.environ.get(ENV_CLI), shutil.which("TwitchDownloaderCLI")]
    candidates.append(str(DEFAULT_CLI_DIR / "TwitchDownloaderCLI.exe"))
    candidates.append(str(DEFAULT_CLI_DIR / "TwitchDownloaderCLI"))
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise StreamIngestError(
        "TwitchDownloaderCLI was not found.\n"
        "Download the Windows x64 zip from https://github.com/lay295/TwitchDownloader/releases "
        f"and unzip it to {DEFAULT_CLI_DIR}, or set {ENV_CLI}."
    )


def parse_time(value: str | float | int | None) -> float:
    """Parse ``90``, ``1:30``, ``1:02:03`` or ``1h2m3s`` into seconds (0 if empty)."""
    if value in (None, "", 0):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    if ":" in text:
        seconds = 0.0
        for part in text.split(":"):
            seconds = seconds * 60 + float(part)
        return seconds
    total = 0.0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", text):
        total += float(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    if total == 0.0:
        raise StreamIngestError(f"Could not read the time {value!r} (try 1:02:03 or 90).")
    return total


def disk_free_gb(path: Path) -> float:
    target = path
    while not target.exists() and target.parent != target:
        target = target.parent
    return shutil.disk_usage(target).free / 1024**3


def _run_cli(args: list[str], what: str) -> None:
    command = [find_cli(), *args, "--collision", "Overwrite", "--banner", "false"]
    log.info("Running %s", " ".join(command))
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise StreamIngestError(f"Could not start TwitchDownloaderCLI: {exc}") from exc
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-800:]
        raise StreamIngestError(f"{what} failed (exit {result.returncode}).\n{tail}")


def ingest_twitch_vod(
    url_or_id: str,
    *,
    start: str | float | None = None,
    end: str | float | None = None,
    quality: str = "720p60",
    min_free_gb: float = 10.0,
    skip_video: bool = False,
) -> StreamSource:
    """Download a Twitch VOD and its chat into ``<root>/streams/<vod_id>/``.

    ``start``/``end`` trim the download (a 30-minute slice is enough for a first test).
    Re-running with the same arguments reuses files that are already there.
    """
    vod_id = twitch_vod_id(url_or_id)
    if vod_id is None:
        raise StreamIngestError(f"{url_or_id!r} does not look like a Twitch VOD link or id.")

    trim_start = parse_time(start)
    trim_end = parse_time(end)
    # A trimmed download is a different file from the full VOD: key the folder by the trim
    # so re-running with another range never reuses the wrong video.
    suffix = f"_{int(trim_start)}-{int(trim_end)}" if (trim_start or trim_end) else ""
    folder = streams_dir() / f"{vod_id}{suffix}"
    folder.mkdir(parents=True, exist_ok=True)

    free = disk_free_gb(folder)
    if free < min_free_gb:
        raise StreamIngestError(
            f"Only {free:.1f} GB free; need at least {min_free_gb:.0f} GB. Free some space first."
        )

    trim_args: list[str] = []
    if trim_start:
        trim_args += ["--beginning", f"{int(trim_start)}s"]
    if trim_end:
        trim_args += ["--ending", f"{int(trim_end)}s"]

    video = folder / "vod.mp4"
    if not skip_video and not (video.exists() and video.stat().st_size > 0):
        _run_cli(
            [
                "videodownload",
                "--id",
                vod_id,
                "-o",
                str(video),
                "--quality",
                quality,
                "--ffmpeg-path",
                ffmpeg.ffmpeg_path(),
                *trim_args,
            ],
            "Video download",
        )

    chat_raw = folder / "chat_raw.json"
    if not (chat_raw.exists() and chat_raw.stat().st_size > 0):
        _run_cli(["chatdownload", "--id", vod_id, "-o", str(chat_raw), *trim_args], "Chat download")

    return _finish(
        folder,
        video,
        chat_raw,
        vod_id=vod_id,
        url=url_or_id,
        trim_start_s=trim_start,
    )


def ingest_local(
    video: Path,
    *,
    chat_json: Path | None = None,
    vod_id: str | None = None,
    trim_start_s: float = 0.0,
) -> StreamSource:
    """Store a local video (and optionally a TwitchDownloader chat JSON) as a stream."""
    video = Path(video)
    if not video.is_file():
        raise StreamIngestError(f"{video} does not exist.")
    vod_id = vod_id or re.sub(r"[^\w-]+", "-", video.stem).strip("-")[:40] or "local"
    folder = streams_dir() / vod_id
    folder.mkdir(parents=True, exist_ok=True)

    target = folder / "vod.mp4"
    if not target.exists():
        shutil.copy2(video, target)
    chat_raw: Path | None = None
    if chat_json is not None:
        chat_raw = folder / "chat_raw.json"
        shutil.copy2(chat_json, chat_raw)
    return _finish(folder, target, chat_raw, vod_id=vod_id, url=str(video), trim_start_s=trim_start_s)


def _finish(
    folder: Path,
    video: Path,
    chat_raw: Path | None,
    *,
    vod_id: str,
    url: str,
    trim_start_s: float,
) -> StreamSource:
    chat_path: Path | None = None
    streamer = ""
    title = ""
    duration = 0.0

    if video.exists():
        try:
            duration = ffmpeg.probe(video).duration_s
        except ffmpeg.FFmpegError as exc:
            raise StreamIngestError(f"{video.name} could not be read: {exc}") from exc

    if chat_raw is not None and chat_raw.exists():
        raw = json.loads(chat_raw.read_text(encoding="utf-8"))
        log_ = parse_twitchdownloader_json(raw)
        # A trimmed chat download keeps original VOD offsets in each comment, so shift
        # by the trim start to match the trimmed video file.
        video_info = raw.get("video") or {}
        shift = float(video_info.get("start") or trim_start_s or 0.0)
        if shift:
            log_ = log_.shifted(-shift)
        log_.video_id = log_.video_id or vod_id
        if duration:
            log_.duration_s = duration
        streamer = log_.streamer
        title = str((raw.get("video") or {}).get("title", "") or "")
        chat_path = folder / "chat.json"
        log_.save(chat_path)
        if len(log_) == 0:
            log.warning("The chat replay for %s has no messages.", vod_id)

    source = StreamSource(
        vod_id=vod_id,
        folder=folder,
        video=video,
        chat_path=chat_path,
        streamer=streamer,
        title=title,
        url=url,
        trim_start_s=trim_start_s,
        duration_s=duration,
    )
    meta = {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(source).items()}
    (folder / "stream.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return source


def load_stream(vod_id: str) -> StreamSource:
    """Reload a previously ingested stream by VOD id."""
    folder = streams_dir() / vod_id
    meta_path = folder / "stream.json"
    if not meta_path.exists():
        raise StreamIngestError(f"No stored stream {vod_id!r} (looked in {folder}).")
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    return StreamSource(
        vod_id=data["vod_id"],
        folder=Path(data["folder"]),
        video=Path(data["video"]),
        chat_path=Path(data["chat_path"]) if data.get("chat_path") else None,
        streamer=data.get("streamer", ""),
        title=data.get("title", ""),
        url=data.get("url", ""),
        trim_start_s=data.get("trim_start_s", 0.0),
        duration_s=data.get("duration_s", 0.0),
    )
