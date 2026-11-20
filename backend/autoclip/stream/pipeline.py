"""Orchestration for ``clip stream`` (step 2e).

Two phases, because the clips are chosen by Claude in a Claude Code session
(the ``/clip`` skill) rather than by an API call:

1. ``prepare``  ingest -> transcribe -> chat-hype peaks -> ``candidates.json``
2. ``render``   ``highlights.json`` (written by the skill) -> layouts -> rules -> export

``clip stream <vod> --campaign X`` runs phase 1, and runs phase 2 as soon as a
``highlights.json`` exists for the job. Everything is resumable: each phase reuses
the files the earlier run left in ``work/<job_id>/``.

highlights.json (written by the /clip skill) looks like::

    {"clips": [{
        "start_word_index": 1204, "end_word_index": 1390,
        "title": "...", "hook": "...", "caption": "...", "hashtags": ["GTA6"],
        "score": 85, "reason": "...",
        "spoiler_level": "none" | "reaction-to-spoiler" | "raw-cinematic",
        "layout": "track" | "facecam" | "reaction",
        "blur_windows": [[2.0, 6.5]]        # clip-relative seconds, REACTION only
    }]}
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .. import paths
from ..config import Settings
from ..db import store
from ..db.models import Clip, Export, Job, Source, new_id
from ..pipeline import captions, cutqa, export, ffmpeg, highlights
from ..pipeline.boundaries import refine
from ..pipeline.runner import PipelineRunner
from ..providers import ClipCandidate
from .campaigns import Campaign
from .chat import ChatLog
from .ingest import StreamSource

log = logging.getLogger(__name__)

SPOILER_LEVELS = ("none", "reaction-to-spoiler", "raw-cinematic")
LAYOUTS = ("track", "facecam", "reaction")

#: Words of transcript shown around each hype window so the skill sees the lead-up.
CONTEXT_MARGIN_S = 20.0


class StreamPipelineError(RuntimeError):
    """The stream pipeline cannot continue (message is user-facing)."""


@dataclass
class ClipMeta:
    """Per-clip choices made by the /clip skill that AutoClip's Clip row cannot hold."""

    spoiler_level: str = "none"
    layout: str = "track"
    blur_windows: list[tuple[float, float]] = field(default_factory=list)
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)


@dataclass
class ClipOutcome:
    rank: int
    title: str
    hook: str
    start_s: float
    end_s: float
    layout_requested: str
    layout_used: str
    spoiler_level: str
    status: str  # exported | rejected | blocked | failed
    qa_score: int = 0
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    path: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Phase 1: prepare
# --------------------------------------------------------------------------


@dataclass
class Prepared:
    job: Job
    source: Source
    runner: PipelineRunner
    candidates_path: Path
    highlights_path: Path


def make_settings(settings: Settings, campaign: Campaign) -> Settings:
    """Apply stream defaults: large-v3-turbo on the GPU, campaign duration limits."""
    settings = settings.model_copy(deep=True)
    if settings.whisper.model == "small":  # the AutoClip default; a stream deserves better
        settings.whisper.model = "large-v3-turbo"
    settings.clips.min_duration_s = campaign.min_duration_s
    settings.clips.max_duration_s = campaign.max_duration_s
    return settings


def job_for_stream(stream: StreamSource, settings: Settings) -> tuple[Job, Source]:
    """Create (or reuse) the AutoClip source + job rows for a stored stream.

    The video is referenced in place (not copied): a 3 hour VOD is several GB.
    """
    sources = [s for s in store.list_sources(limit=500) if s.path == str(stream.video)]
    if sources:
        source = sources[0]
    else:
        info = ffmpeg.probe(stream.video)
        source = store.create_source(
            Source(
                id=new_id(),
                type="upload",
                path=str(stream.video),
                title=stream.title or f"{stream.streamer or 'stream'} {stream.vod_id}",
                url=stream.url or None,
                filename=stream.video.name,
                channel=stream.streamer or None,
                duration_s=info.duration_s,
                width=info.width,
                height=info.height,
                fps=info.fps,
                has_audio=info.has_audio,
                has_video=info.has_video,
            )
        )
    existing = [j for j in store.list_jobs(limit=200) if j.source_id == source.id]
    if existing:
        return existing[0], source
    job = store.create_job(
        Job(
            id=new_id(),
            source_id=source.id,
            provider="file",
            settings=settings.model_dump(mode="json"),
        )
    )
    return job, source


def prepare(
    stream: StreamSource,
    campaign: Campaign,
    *,
    settings: Settings,
    on_status: Callable[[str], None] | None = None,
    max_candidates: int = 15,
) -> Prepared:
    """Transcribe, score chat hype and write ``candidates.json``."""
    from ..pipeline import hype  # imported lazily: written by a parallel task

    say = on_status or (lambda _msg: None)
    settings = make_settings(settings, campaign)
    job, source = job_for_stream(stream, settings)
    runner = PipelineRunner(job, source, settings=settings)
    store.update_job(job.id, status="running")

    say("Extracting audio")
    audio = runner._stage_prepare()
    say(f"Transcribing with {settings.whisper.model} (this is the slow step)")
    transcript = runner._stage_transcribe(audio)
    silences = runner._load_or_detect_silences(audio)

    chat = stream.load_chat()
    say("Scoring chat hype" if chat else "No chat available: scoring audio loudness only")
    loudness = hype.loudness_series(audio)
    peaks = hype.compute_hype(
        chat or ChatLog(duration_s=source.duration_s),
        loudness=loudness,
        duration_s=source.duration_s,
        config=hype.HypeConfig(top_n=max_candidates),
    )
    if not peaks:
        raise StreamPipelineError("No hype peaks found: chat and audio were flat everywhere.")

    candidates = []
    for rank, peak in enumerate(peaks, start=1):
        lo = max(0.0, peak.window_start - CONTEXT_MARGIN_S)
        hi = peak.window_end + CONTEXT_MARGIN_S
        first, last = transcript.indices_in_range(lo, hi)
        last = max(first, last - 1)
        candidates.append(
            {
                "rank": rank,
                "peak_t": peak.t,
                "hype_score": round(peak.score, 2),
                "window_start_s": round(peak.window_start, 1),
                "window_end_s": round(peak.window_end, 1),
                "hype_reasons": peak.reasons,
                "chat_sample": peak.sample_messages,
                "first_word": first,
                "last_word": last,
                "transcript": highlights.render_window_text(transcript, first, last),
            }
        )

    work = runner.workspace.root
    candidates_path = work / "candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "job_id": job.id,
                "stream": {
                    "vod_id": stream.vod_id,
                    "streamer": stream.streamer,
                    "title": stream.title,
                    "duration_s": source.duration_s,
                },
                "campaign": campaign.name,
                "limits": {
                    "min_duration_s": campaign.min_duration_s,
                    "max_duration_s": campaign.max_duration_s,
                    "required_hashtags": campaign.required_hashtags,
                    "required_mentions": campaign.required_mentions,
                    "spoiler_policy": campaign.spoiler_policy,
                    "today_only": campaign.today_only,
                },
                "transcript_words": len(transcript.words),
                "silences": len(silences),
                "candidates": candidates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    say(f"Wrote {len(candidates)} candidate windows")
    return Prepared(
        job=job,
        source=source,
        runner=runner,
        candidates_path=candidates_path,
        highlights_path=work / "highlights.json",
    )


# --------------------------------------------------------------------------
# Phase 2: render
# --------------------------------------------------------------------------


def resolve_overlay(campaign: Campaign) -> Path | None:
    """The campaign's required logo file, or None when it is not required / not present."""
    if not campaign.required_overlay.strip():
        return None
    candidate = Path(campaign.required_overlay)
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parents[3] / "campaigns" / "assets" / candidate
    return candidate if candidate.is_file() else None


def load_highlights(path: Path) -> list[tuple[ClipCandidate, ClipMeta]]:
    """Parse and validate highlights.json, with errors a human can act on."""
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StreamPipelineError(f"{path} is not valid JSON: {exc}") from exc
    items = raw.get("clips")
    if not isinstance(items, list) or not items:
        raise StreamPipelineError(f"{path} has no 'clips' list.")

    parsed: list[tuple[ClipCandidate, ClipMeta]] = []
    for position, item in enumerate(items, start=1):
        try:
            candidate = ClipCandidate.model_validate(
                {
                    k: item[k]
                    for k in ("start_word_index", "end_word_index", "title", "hook", "score")
                    if k in item
                }
                | {"reason": item.get("reason", "")}
            )
        except Exception as exc:
            raise StreamPipelineError(f"clips[{position}] is invalid: {exc}") from exc
        spoiler = item.get("spoiler_level", "none")
        layout = item.get("layout", "track")
        if spoiler not in SPOILER_LEVELS:
            raise StreamPipelineError(
                f"clips[{position}].spoiler_level {spoiler!r} must be one of {SPOILER_LEVELS}"
            )
        if layout not in LAYOUTS:
            raise StreamPipelineError(
                f"clips[{position}].layout {layout!r} must be one of {LAYOUTS}"
            )
        parsed.append(
            (
                candidate,
                ClipMeta(
                    spoiler_level=spoiler,
                    layout=layout,
                    blur_windows=[(float(a), float(b)) for a, b in item.get("blur_windows", [])],
                    caption=str(item.get("caption", "")),
                    hashtags=[str(h) for h in item.get("hashtags", [])],
                ),
            )
        )
    return parsed


def build_clip_rows(
    prepared: Prepared,
    picks: list[tuple[ClipCandidate, ClipMeta]],
    campaign: Campaign,
) -> tuple[list[tuple[Clip, ClipMeta]], list[ClipOutcome]]:
    """Turn picks into Clip rows (boundary-refined). Raw cinematics are rejected here."""
    runner = prepared.runner
    from ..pipeline.transcript import Transcript

    transcript = Transcript.load(runner.workspace.transcript)
    silences = runner._load_or_detect_silences(runner.workspace.audio)
    rows: list[tuple[Clip, ClipMeta]] = []
    outcomes: list[ClipOutcome] = []

    for candidate, meta in picks:
        if meta.spoiler_level == "raw-cinematic":
            outcomes.append(
                ClipOutcome(
                    rank=0,
                    title=candidate.title,
                    hook=candidate.hook,
                    start_s=0.0,
                    end_s=0.0,
                    layout_requested=meta.layout,
                    layout_used="-",
                    spoiler_level=meta.spoiler_level,
                    status="rejected",
                    notes=["raw cinematic footage: rejected by the spoiler filter"],
                )
            )
            continue
        boundary = refine(
            transcript,
            candidate.start_word_index,
            candidate.end_word_index,
            silences=silences,
            min_duration_s=campaign.min_duration_s,
            max_duration_s=campaign.max_duration_s,
        )
        if boundary is None:
            outcomes.append(
                ClipOutcome(
                    rank=0,
                    title=candidate.title,
                    hook=candidate.hook,
                    start_s=0.0,
                    end_s=0.0,
                    layout_requested=meta.layout,
                    layout_used="-",
                    spoiler_level=meta.spoiler_level,
                    status="failed",
                    notes=["no valid cut within the campaign's duration limits"],
                )
            )
            continue
        clip = Clip(
            id=new_id(),
            job_id=prepared.job.id,
            start_s=boundary.start_s,
            end_s=boundary.end_s,
            start_word=boundary.start_word,
            end_word=boundary.end_word,
            title=candidate.title.strip()
            or transcript.text_between(
                boundary.start_word, min(boundary.start_word + 8, boundary.end_word)
            ),
            hook=candidate.hook.strip(),
            score=candidate.score,
            reason=candidate.reason.strip(),
        )
        rows.append((clip, meta))

    rows.sort(key=lambda pair: pair[0].score, reverse=True)
    for rank, (clip, _meta) in enumerate(rows, start=1):
        clip.rank = rank
    return rows, outcomes


def write_report(outcomes: list[ClipOutcome], destination: Path, *, campaign: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "report.json").write_text(
        json.dumps([asdict(o) for o in outcomes], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = [f"# Clip report: {campaign}", ""]
    for o in outcomes:
        lines.append(
            f"## {o.status.upper()}  #{o.rank}  {o.title}  "
            f"(QA {o.qa_score}, {o.layout_used}, spoiler: {o.spoiler_level})"
        )
        lines.append(f"- source time: {o.start_s:.0f}s-{o.end_s:.0f}s  hook: {o.hook}")
        if o.caption:
            lines.append(f"- caption: {o.caption}  tags: {' '.join('#' + h.lstrip('#') for h in o.hashtags)}")
        for v in o.violations:
            lines.append(f"- BLOCKED: {v}")
        for n in o.notes:
            lines.append(f"- note: {n}")
        if o.path:
            lines.append(f"- file: {o.path}")
        lines.append("")
    (destination / "report.md").write_text("\n".join(lines), encoding="utf-8")


def render(
    prepared: Prepared,
    campaign: Campaign,
    *,
    stream: StreamSource,
    on_status: Callable[[str], None] | None = None,
) -> list[ClipOutcome]:
    """Render every pick in highlights.json that passes the spoiler filter and the rules."""
    from ..pipeline import layouts, rules
    from ..pipeline.facecam import detect_facecam
    from ..pipeline.profanity import bleep_audio_filter, censor_words, profane_intervals
    from ..pipeline.transcript import Transcript

    say = on_status or (lambda _msg: None)
    picks = load_highlights(prepared.highlights_path)
    rows, outcomes = build_clip_rows(prepared, picks, campaign)
    if not rows:
        raise StreamPipelineError("No usable clips: every pick was rejected or could not be cut.")

    runner = prepared.runner
    settings = runner.settings
    transcript = Transcript.load(runner.workspace.transcript)
    source_path = Path(prepared.source.path)
    out_dir = paths.exports_dir() / prepared.job.id
    out_dir.mkdir(parents=True, exist_ok=True)
    style = captions.get_style(settings.export.caption_style)
    ratio = "9:16"
    stream_date = _stream_date(stream)
    overlay = resolve_overlay(campaign)
    disclosure = campaign.disclosure_text if campaign.disclosure_required else ""

    store.replace_clips(prepared.job.id, [clip for clip, _ in rows])

    for clip, meta in rows:
        say(f"Clip {clip.rank}/{len(rows)}: {clip.title}")
        notes: list[str] = []
        words = transcript.slice(clip.start_word, clip.end_word)
        duration = clip.end_s - clip.start_s

        # -- layout ----------------------------------------------------------
        layout = layouts.Layout(meta.layout)
        if meta.spoiler_level == "reaction-to-spoiler":
            # Rockstar-sensitive moment: the reaction is the clip. Force the REACTION layout.
            layout = layouts.Layout.REACTION
        plan = None
        if layout in (layouts.Layout.FACECAM, layouts.Layout.REACTION):
            cam = detect_facecam(source_path, clip.start_s, clip.end_s)
            if cam is None:
                notes.append(f"no facecam found: {layout.value} layout fell back to track")
                layout = layouts.Layout.TRACK
            else:
                blur = [layouts.BlurWindow(a, b) for a, b in meta.blur_windows]
                if meta.spoiler_level == "reaction-to-spoiler" and not blur:
                    notes.append("reaction-to-spoiler clip has no blur window (check the reveal)")
                plan = layouts.default_plan(layout, cam, blur)
        crop_path = None
        if plan is None:
            from ..pipeline.reframe import ReframeConfig, build_crop_path

            crop_path = build_crop_path(
                source_path,
                start_s=clip.start_s,
                end_s=clip.end_s,
                transcript=transcript,
                config=ReframeConfig(aspect_w=9, aspect_h=16),
            )

        # -- rules -----------------------------------------------------------
        result = rules.check_clip(
            campaign,
            rules.ClipFacts(
                duration_s=duration,
                title=clip.title,
                caption=meta.caption,
                hashtags=meta.hashtags,
                hook=clip.hook,
                transcript_text=" ".join(w.text for w in words),
                spoiler_level=meta.spoiler_level,
                source_stream_date=stream_date,
                has_captions=True,
                has_hook=bool(clip.hook),
                reframed=True,
                disclosure_shown=bool(disclosure),
                overlay_applied=overlay is not None,
            ),
        )
        if not result.passed:
            outcomes.append(
                ClipOutcome(
                    rank=clip.rank,
                    title=clip.title,
                    hook=clip.hook,
                    start_s=clip.start_s,
                    end_s=clip.end_s,
                    layout_requested=meta.layout,
                    layout_used=layout.value,
                    spoiler_level=meta.spoiler_level,
                    status="blocked",
                    qa_score=result.qa_score,
                    violations=[v.message for v in result.violations if v.blocking],
                    notes=notes,
                    caption=meta.caption,
                    hashtags=meta.hashtags,
                )
            )
            store.update_clip(clip.id, status="discarded")
            continue

        # -- swear filter ----------------------------------------------------
        audio_filter = ""
        render_words = words
        if campaign.swear_filter != "off":
            render_words = censor_words(words, campaign.swear_filter)
            if campaign.swear_filter == "bleep":
                intervals = [
                    (a - clip.start_s, b - clip.start_s) for a, b in profane_intervals(words)
                ]
                audio_filter = bleep_audio_filter(intervals)

        destination = out_dir / export.output_filename(clip.title or f"clip-{clip.rank}", ratio)
        request = export.ExportRequest(
            source=source_path,
            destination=destination,
            start_s=clip.start_s,
            end_s=clip.end_s,
            crop_path=crop_path,  # type: ignore[arg-type]
            words=render_words,
            style=style,
            ratio=ratio,
            layout_plan=plan,
            hook_text=clip.hook,
            disclosure_text=disclosure,
            disclosure_duration_s=campaign.disclosure_duration_s,
            overlay_path=overlay,
            extra_audio_filter=audio_filter,
        )
        try:
            export.export_clip(
                request, work_dir=runner.workspace.captions_dir, settings=settings.export
            )
        except export.ExportError as exc:
            outcomes.append(
                ClipOutcome(
                    rank=clip.rank,
                    title=clip.title,
                    hook=clip.hook,
                    start_s=clip.start_s,
                    end_s=clip.end_s,
                    layout_requested=meta.layout,
                    layout_used=layout.value,
                    spoiler_level=meta.spoiler_level,
                    status="failed",
                    notes=[*notes, str(exc)[:300]],
                )
            )
            continue

        qa_score = result.qa_score
        edge_issues = cutqa.check_clip_edges(
            destination,
            [w.text for w in words[:4]],
            [w.text for w in words[-4:]],
        )
        for issue in edge_issues:
            notes.append(f"cut-point {issue.severity} ({issue.edge}): {issue.message}")
            qa_score = max(0, qa_score - (25 if issue.severity == "error" else 5))

        store.create_export(
            Export(
                id=new_id(),
                clip_id=clip.id,
                path=str(destination),
                ratio=ratio,
                style=style.key,
                size_bytes=destination.stat().st_size,
            )
        )
        store.update_clip(clip.id, status="exported")
        outcomes.append(
            ClipOutcome(
                rank=clip.rank,
                title=clip.title,
                hook=clip.hook,
                start_s=clip.start_s,
                end_s=clip.end_s,
                layout_requested=meta.layout,
                layout_used=layout.value,
                spoiler_level=meta.spoiler_level,
                status="exported",
                qa_score=qa_score,
                notes=notes,
                path=str(destination),
                caption=meta.caption,
                hashtags=meta.hashtags,
            )
        )

    store.update_job(prepared.job.id, status="done", progress=1.0)
    write_report(outcomes, out_dir, campaign=campaign.name)
    return outcomes


def _stream_date(stream: StreamSource):
    """The VOD's date when known (used by 'today's stream only' campaigns)."""
    from datetime import UTC, datetime

    meta = stream.folder / "chat_raw.json"
    try:
        raw = json.loads(meta.read_text(encoding="utf-8"))
        created = (raw.get("video") or {}).get("created_at")
        if created:
            return datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    except (OSError, ValueError):
        pass
    return datetime.fromtimestamp(stream.video.stat().st_mtime, tz=UTC)
