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
        "blur_word_ranges": [[1250, 1262]],  # word-index ranges to blur (the reveal), REACTION
        "mentions": []                       # @mentions the campaign requires in the post
    }]}
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .. import paths
from ..config import Settings
from ..db import store
from ..db.models import Clip, Export, Job, Source, new_id
from ..pipeline import captions, cutqa, export, ffmpeg, highlights, sfx
from ..pipeline.boundaries import refine
from ..pipeline.runner import PipelineRunner
from ..providers import ClipCandidate
from .campaigns import Campaign
from .chat import ChatLog
from .ingest import StreamSource, twitch_vod_id

log = logging.getLogger(__name__)

SPOILER_LEVELS = ("none", "reaction-to-spoiler", "raw-cinematic")
LAYOUTS = ("track", "facecam", "reaction")

#: Words of transcript shown around each hype window so the skill sees the lead-up.
CONTEXT_MARGIN_S = 20.0


class StreamPipelineError(RuntimeError):
    """The stream pipeline cannot continue (message is user-facing)."""


class StreamSliceSkipped(StreamPipelineError):
    """A campaign guard excludes the slice without retrying it."""


def dylan_campaign(campaign: Campaign | str) -> bool:
    name = campaign if isinstance(campaign, str) else campaign.name
    return name in {"dylan-page-marathon", "Dylan Page GTA 6 Marathon"}


def require_campaign_camera(stream: StreamSource, campaign: Campaign | str) -> None:
    if isinstance(campaign, Campaign) and campaign.camera_box is not None:
        return
    if dylan_campaign(campaign):
        from ..pipeline.facecam import detect_facecam_geometry

        if detect_facecam_geometry(stream.video, 0, stream.duration_s) is None:
            raise StreamSliceSkipped("Dylan campaign requires a usable camera; no webcam/face detected.")


def no_chat_peaks(audio_peaks, transcript, duration_s: float, limit: int):
    """Pool audio and transcript evidence with equal rank weights, without chat."""
    from ..pipeline.hype import HypePeak
    from ..pipeline.transcript_hype import compute_transcript_hype
    from .fusion import pool_candidates

    pooled = pool_candidates({
        "audio": audio_peaks,
        "transcript": compute_transcript_hype(transcript, duration_s=duration_s, top_n=limit),
    })
    ranked = sorted(pooled, key=lambda p: (-p.rrf, p.t))[:limit]
    return [HypePeak(p.t, p.rrf, p.start, p.end,
                     [f"{name}: {reason}" for name, why in p.reasons.items() for reason in why],
                     []) for p in ranked]


@dataclass
class ClipMeta:
    """Per-clip choices made by the /clip skill that AutoClip's Clip row cannot hold."""

    spoiler_level: str = "none"
    layout: str = "track"
    #: Inclusive word-index ranges whose on-screen time is blurred (the reveal). Word indexes,
    #: not seconds: boundary refinement moves the clip start, so seconds would drift.
    blur_word_ranges: list[tuple[int, int]] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sfx: list[dict] = field(default_factory=list)
    story: dict | None = None


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
    sfx: str = ""
    story: dict | None = None


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
    from . import hype_eval

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
    viewer_clips = []
    try:
        vod_id = twitch_vod_id(stream.vod_id)
        if not vod_id:
            say("Skipping viewer clips: VOD id unknown")
        elif not (
            hype_eval.user_env("TWITCH_CLIENT_ID")
            and hype_eval.user_env("TWITCH_CLIENT_SECRET")
        ):
            say("Skipping viewer clips: Twitch credentials missing")
        else:
            # Match ingest's chat shift: raw video.start takes precedence over the trim.
            shift = stream.trim_start_s
            raw_path = stream.folder / "chat_raw.json"
            if raw_path.exists():
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                shift = float((raw.get("video") or {}).get("start") or shift or 0.0)
            viewer_clips = [
                {
                    "view_count": clip.views,
                    "title": clip.title,
                    "offset_s": clip.offset_s - shift,
                }
                for clip in hype_eval.fetch_viewer_clips(vod_id)
                if 0 <= clip.offset_s - shift < source.duration_s
            ]
            viewer_clips.sort(key=lambda clip: clip["view_count"], reverse=True)
    except Exception:
        # Optional evidence must never prevent preparation; API errors may contain secrets.
        viewer_clips = []
        say("Skipping viewer clips: fetch failed")

    say("Scoring chat hype" if chat else "No chat available: scoring audio loudness plus transcript hype")
    loudness = hype.loudness_series(audio)
    peaks = hype.compute_hype(
        chat or ChatLog(duration_s=source.duration_s),
        loudness=loudness,
        viewer_clips=[clip["offset_s"] for clip in viewer_clips],
        duration_s=source.duration_s,
        config=hype.HypeConfig(top_n=max_candidates),
    )
    if not chat:
        peaks = no_chat_peaks(peaks, transcript, source.duration_s, max_candidates)
    if not peaks:
        if not chat:
            raise StreamSliceSkipped("No reaction candidates in audio or transcript; slice completed without clips.")
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
                "viewer_clips": [
                    clip
                    for clip in viewer_clips
                    if peak.window_start <= clip["offset_s"] < peak.window_end
                ][:3],
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
                    "viewer_clips_used": len(viewer_clips),
                },
                "campaign": campaign.name,
                "limits": {
                    "min_duration_s": campaign.min_duration_s,
                    "max_duration_s": campaign.max_duration_s,
                    "required_hashtags": campaign.required_hashtags,
                    "required_mentions": campaign.required_mentions,
                    "required_caption_phrases": campaign.required_caption_phrases,
                    "max_title_chars": campaign.max_title_chars,
                    "banned_words": campaign.banned_words,
                    "banned_topics": campaign.banned_topics,
                    "disclosure_required": campaign.disclosure_required,
                    "required_overlay": bool(campaign.required_overlay),
                    "swear_filter": campaign.swear_filter,
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
            candidate = highlights.StoryPick.model_validate(item)
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
                    blur_word_ranges=[
                        (int(a), int(b)) for a, b in item.get("blur_word_ranges", [])
                    ],
                    mentions=[str(m) for m in item.get("mentions", [])],
                    caption=str(item.get("caption", "")),
                    hashtags=[str(h) for h in item.get("hashtags", [])],
                    sfx=item.get("sfx", []),
                    story=candidate.story.model_dump() if candidate.story is not None else None,
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
                    story=meta.story,
                    notes=["raw cinematic footage: rejected by the spoiler filter"],
                )
            )
            continue
        story_checks: list[highlights.StoryVerdict] = []
        boundary = refine(
            transcript,
            candidate.start_word_index,
            candidate.end_word_index,
            silences=silences,
            min_duration_s=campaign.min_duration_s,
            max_duration_s=campaign.max_duration_s,
            pick=candidate,
            on_story_check=story_checks.append,
        )
        for verdict in story_checks:
            for reason in verdict.reasons:
                note = f"story {verdict.status}: {reason}"
                if note not in meta.warnings:
                    meta.warnings.append(note)
        rejected = any(verdict.status == "reject" for verdict in story_checks)
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
                    status="rejected" if rejected else "failed",
                    story=meta.story,
                    notes=list(meta.warnings) if rejected else [
                        *meta.warnings, "no valid cut within the campaign's duration limits"
                    ],
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
        meta.warnings.extend(highlights.quality_warnings(clip.end_s - clip.start_s, clip.hook))
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
        if o.sfx:
            lines.append(f"- sfx: {o.sfx}")
        if o.story:
            for name in ("setup", "change", "payoff"):
                beat = o.story[name]
                lines.append(
                    f"- {name}: {beat['start_s']:g}s-{beat['end_s']:g}s: {beat['text']}"
                )
        if o.caption:
            lines.append(
                f"- caption: {o.caption}  tags: {' '.join('#' + h.lstrip('#') for h in o.hashtags)}"
            )
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
    from ..pipeline.facecam import detect_facecam_geometry, manual_facecam_geometry
    from ..pipeline.profanity import bleep_audio_filter, censor_words, profane_intervals
    from ..pipeline.transcript import Transcript

    say = on_status or (lambda _msg: None)
    picks = load_highlights(prepared.highlights_path)
    rows, outcomes = build_clip_rows(prepared, picks, campaign)
    out_dir = paths.exports_dir() / prepared.job.id
    if not rows:
        write_report(outcomes, out_dir, campaign=campaign.name)
        raise StreamPipelineError("No usable clips: every pick was rejected or could not be cut.")

    runner = prepared.runner
    settings = runner.settings
    transcript = Transcript.load(runner.workspace.transcript)
    source_path = Path(prepared.source.path)
    out_dir.mkdir(parents=True, exist_ok=True)
    style = captions.get_style(settings.export.caption_style)
    ratio = "9:16"
    stream_date = _stream_date(stream)
    overlay = resolve_overlay(campaign)
    disclosure = campaign.disclosure_text if campaign.disclosure_required else ""

    store.replace_clips(prepared.job.id, [clip for clip, _ in rows])

    for clip, meta in rows:
        say(f"Clip {clip.rank}/{len(rows)}: {clip.title}")
        notes: list[str] = list(meta.warnings)
        words = transcript.slice(clip.start_word, clip.end_word)
        duration = clip.end_s - clip.start_s

        # -- layout ----------------------------------------------------------
        layout = layouts.Layout(meta.layout)
        if dylan_campaign(campaign) or campaign.camera_box is not None:
            layout = layouts.Layout.FACECAM
        if meta.spoiler_level == "reaction-to-spoiler":
            # Rockstar-sensitive moment: the reaction is the clip. Force the REACTION layout.
            layout = layouts.Layout.REACTION
        plan = None
        if layout in (layouts.Layout.FACECAM, layouts.Layout.REACTION):
            if campaign.camera_box is not None:
                info = ffmpeg.probe(source_path)
                camera = manual_facecam_geometry(campaign.camera_box, info.width, info.height)
            else:
                camera = detect_facecam_geometry(source_path, clip.start_s, clip.end_s)
            if camera is not None and dylan_campaign(campaign) and campaign.camera_box is None:
                # A camera seen in the intro alone is insufficient. Require a usable
                # camera throughout the cut, checking every five-second interval.
                for offset in range(0, max(1, math.ceil(duration)), 5):
                    lo = clip.start_s + offset
                    if detect_facecam_geometry(source_path, lo, min(lo + 5, clip.end_s)) is None:
                        camera = None
                        break
            if camera is None:
                if dylan_campaign(campaign):
                    outcomes.append(ClipOutcome(
                        rank=clip.rank, title=clip.title, hook=clip.hook,
                        start_s=clip.start_s, end_s=clip.end_s,
                        layout_requested=meta.layout, layout_used="-",
                        spoiler_level=meta.spoiler_level, status="rejected",
                        notes=["Dylan camera missing in clip; gameplay-only footage skipped"],
                    ))
                    store.update_clip(clip.id, status="discarded")
                    continue
                notes.append(f"no facecam found: {layout.value} layout fell back to track")
                layout = layouts.Layout.TRACK
            else:
                blur = _blur_windows(meta.blur_word_ranges, transcript, clip, notes)
                if meta.spoiler_level == "reaction-to-spoiler" and not blur:
                    notes.append("reaction-to-spoiler clip has no blur window (check the reveal)")
                plan = layouts.default_plan(layout, camera.webcam, blur, face_crop=camera.face_crop)
                plan.exact_camera_crop = campaign.camera_box is not None
                if campaign.camera_split is not None:
                    plan.cam_fraction = campaign.camera_split
                elif dylan_campaign(campaign):
                    plan.cam_fraction = 0.75

        # -- rules -----------------------------------------------------------
        result = rules.check_clip(
            campaign,
            rules.ClipFacts(
                duration_s=duration,
                title=clip.title,
                caption=meta.caption,
                hashtags=meta.hashtags,
                mentions=meta.mentions,
                hook=clip.hook,
                transcript_text=" ".join(w.text for w in words),
                spoiler_level=meta.spoiler_level,
                source_stream_date=stream_date,
                has_captions=bool(words),
                reaction_layout_ok=not (
                    meta.spoiler_level == "reaction-to-spoiler"
                    and not (plan is not None and plan.layout == layouts.Layout.REACTION)
                ),
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
                    story=meta.story,
                    qa_score=result.qa_score,
                    violations=[v.message for v in result.violations if v.blocking],
                    notes=notes,
                    caption=meta.caption,
                    hashtags=meta.hashtags,
                )
            )
            store.update_clip(clip.id, status="discarded")
            continue

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

        # -- swear filter ----------------------------------------------------
        audio_filter = ""
        muted: list[tuple[float, float]] = []
        render_words = words
        if campaign.swear_filter != "off":
            render_words = censor_words(words, campaign.swear_filter)
            if campaign.swear_filter == "bleep":
                intervals = [
                    (max(0.0, a - clip.start_s), min(duration, b - clip.start_s))
                    for a, b in profane_intervals(words)
                ]
                muted = [iv for iv in intervals if iv[1] > iv[0]]
                audio_filter = bleep_audio_filter(muted)

        destination = out_dir / export.output_filename(clip.title or f"clip-{clip.rank}", ratio)
        effect_name = ""
        if not meta.sfx and settings.auto_sfx:
            try:
                from ..pipeline.sfx_auto import suggest_events

                meta.sfx = suggest_events(
                    runner.workspace.audio, clip.start_s, clip.end_s, seed=clip.id,
                )
            except Exception as exc:
                warning = f"auto sfx warning: {exc}; rendering without sfx"
                log.warning(warning)
                notes.append(warning)
        try:
            effects = sfx.prepare_events(meta.sfx, duration)
        except (ValueError, TypeError, ffmpeg.FFmpegError) as exc:
            warning = f"sfx warning: {exc}; rendering without sfx"
            meta.warnings.append(warning)
            notes.append(warning)
            meta.sfx = []
        else:
            if effects:
                effect_name = effects[0].event.name
                notes.append(f"sfx: {effect_name}")
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
            sfx=meta.sfx,
        )
        try:
            export.export_clip(
                request, work_dir=runner.workspace.captions_dir, settings=settings.export
            )
        except Exception as exc:  # one bad clip must not abort the other clips' renders
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
                    story=meta.story,
                    notes=[*notes, str(exc)[:300]],
                )
            )
            continue

        qa_score = result.qa_score
        edge_issues = cutqa.check_clip_edges(
            destination,
            _audible_words(render_words, clip.start_s, muted)[:4],
            _audible_words(render_words, clip.start_s, muted)[-4:],
        )
        dark_issue = cutqa.check_dark_opening(destination, plan)
        if dark_issue:
            edge_issues.append(dark_issue)
        for issue in edge_issues:
            label = issue.code or "cut-point"
            notes.append(f"{label} {issue.severity} ({issue.edge}): {issue.message}")
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
                sfx=effect_name,
                story=meta.story,
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


def _audible_words(words, clip_start_s: float, muted: list[tuple[float, float]]) -> list[str]:
    """Words that are really audible in the render (bleeped/masked ones cannot be re-heard)."""
    keep = []
    for w in words:
        a, b = w.start - clip_start_s, w.end - clip_start_s
        if "*" in w.text or any(a < hi + 0.1 and b > lo - 0.1 for lo, hi in muted):
            continue
        keep.append(w.text)
    return keep


def _blur_windows(ranges: list[tuple[int, int]], transcript, clip: Clip, notes: list[str]) -> list:
    """Word-index ranges -> clip-relative BlurWindows, using measured word times."""
    from ..pipeline import layouts

    duration = clip.end_s - clip.start_s
    windows = []
    for first, last in ranges:
        lo, hi = transcript.time_range(first, last)
        start = max(0.0, lo - clip.start_s - 0.15)  # a beat early: the reveal precedes the words
        end = min(duration, hi - clip.start_s + 0.15)
        if end <= start:
            notes.append(f"blur words {first}-{last} fall outside the clip; ignored")
            continue
        try:
            windows.append(layouts.BlurWindow(start, end))
        except ValueError as exc:
            notes.append(f"blur words {first}-{last} rejected: {exc}")
    return windows


def _stream_date(stream: StreamSource):
    """The VOD's date when known (used by 'today's stream only' campaigns)."""
    from datetime import datetime

    meta = stream.folder / "chat_raw.json"
    try:
        raw = json.loads(meta.read_text(encoding="utf-8"))
        created = (raw.get("video") or {}).get("created_at")
        if created:
            return datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    except (OSError, ValueError):
        pass
    return None  # unknown: a file's mtime is the download time, never the stream date
