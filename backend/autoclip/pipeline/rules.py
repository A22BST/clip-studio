"""Keep campaign checks deterministic and separate from media rendering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..stream.campaigns import Campaign


@dataclass
class ClipFacts:
    duration_s: float
    title: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    hook: str = ""
    transcript_text: str = ""
    spoiler_level: str = "none"
    source_stream_date: datetime | None = None
    now: datetime | None = None
    has_captions: bool = True
    has_hook: bool = True
    reframed: bool = True
    #: Disclosure text actually burned into the clip start (empty = none).
    disclosure_shown: bool = False
    #: Required streamer overlay actually composited for the whole clip.
    overlay_applied: bool = False
    #: True if any visual in the clip is AI-generated (we never do this; guard anyway).
    ai_visuals: bool = False
    #: False when a reaction-to-spoiler clip could not get the REACTION layout (no camera
    #: found), which would show the reveal unblurred in the full frame.
    reaction_layout_ok: bool = True


@dataclass
class Violation:
    code: str
    message: str
    blocking: bool


@dataclass
class RuleResult:
    passed: bool
    violations: list[Violation]
    qa_score: int


def _utc(value: datetime) -> datetime:
    """Treat naive inputs as UTC so host timezone cannot change approval."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def check_clip(campaign: Campaign, facts: ClipFacts) -> RuleResult:
    """Fail closed on hard rules; light spoiler warnings only reduce the QA score."""
    violations: list[Violation] = []

    def add(code: str, message: str, blocking: bool = True) -> None:
        violations.append(Violation(code, message, blocking))

    if not math.isfinite(facts.duration_s) or facts.duration_s < 0:
        add("invalid_duration", f"invalid duration {facts.duration_s}s")
    elif facts.duration_s < campaign.min_duration_s:
        add("too_short", f"duration {facts.duration_s:.1f}s < min {campaign.min_duration_s:g}s")
    elif facts.duration_s > campaign.max_duration_s:
        add("too_long", f"duration {facts.duration_s:.1f}s > max {campaign.max_duration_s:g}s")

    for kind, required, actual, prefix in (
        ("hashtag", campaign.required_hashtags, facts.hashtags, "#"),
        ("mention", campaign.required_mentions, facts.mentions, "@"),
    ):
        present = {value.strip().lstrip(prefix).casefold() for value in actual}
        for value in required:
            normalized = value.strip().lstrip(prefix).casefold()
            if normalized not in present:
                add(f"missing_{kind}", f"missing required {kind} {prefix}{normalized}")

    text = "\n".join((facts.title, facts.caption, facts.hook, facts.transcript_text)).casefold()
    for word in campaign.banned_words:
        if word.strip() and re.search(r"(?<!\w)" + re.escape(word.casefold()) + r"(?!\w)", text):
            add("banned_word", f"banned word {word!r} present in clip text")
    for topic in campaign.banned_topics:
        if topic.strip() and topic.casefold() in text:
            add("banned_topic", f"banned topic {topic!r} present in clip text")
    if len(facts.title) > campaign.max_title_chars:
        add("title_too_long", f"title length {len(facts.title)} > max {campaign.max_title_chars}")
    for code, present in (
        ("captions", facts.has_captions),
        ("hook", facts.has_hook),
        ("reframe", facts.reframed),
    ):
        if not present:
            add(f"missing_{code}", f"clip requires {code}")

    if campaign.disclosure_required and not facts.disclosure_shown:
        add("missing_disclosure", "campaign requires a paid disclosure at the start of the clip")
    if campaign.required_overlay.strip() and not facts.overlay_applied:
        add(
            "missing_overlay",
            f"campaign requires overlay {campaign.required_overlay!r} for the whole clip",
        )
    if campaign.no_ai_visuals and facts.ai_visuals:
        add("ai_visuals", "campaign forbids AI-generated visuals")
    caption_text = " ".join((facts.caption, facts.title)).casefold()
    for phrase in campaign.required_caption_phrases:
        if phrase.strip() and phrase.casefold() not in caption_text:
            add("missing_caption_phrase", f"caption must contain {phrase!r}")

    if campaign.today_only:
        now = _utc(facts.now or datetime.now(UTC))
        if facts.source_stream_date is None:
            add("missing_stream_date", "today_only requires source_stream_date")
        else:
            source = _utc(facts.source_stream_date)
            age = (now - source).total_seconds() / 3600
            if source.date() != now.date() or not 0 <= age <= campaign.max_age_hours:
                add(
                    "stream_age",
                    f"source stream {source.isoformat()} is not today's stream within "
                    f"max {campaign.max_age_hours:g}h (age {age:.1f}h)",
                )

    if facts.spoiler_level == "reaction-to-spoiler" and not facts.reaction_layout_ok:
        add(
            "reaction_needs_layout",
            "reaction-to-spoiler needs the REACTION layout (camera not found): "
            "the reveal would show unblurred",
        )
    if facts.spoiler_level == "raw-cinematic":
        add("raw_cinematic", "raw-cinematic footage is always prohibited")
    elif facts.spoiler_level == "reaction-to-spoiler" and campaign.spoiler_policy != "none":
        add(
            "spoiler_reaction",
            "reaction-to-spoiler requires spoiler-free title/hook and review",
            campaign.spoiler_policy == "strict",
        )
    elif facts.spoiler_level not in {"none", "reaction-to-spoiler"}:
        add("invalid_spoiler_level", f"unknown spoiler level {facts.spoiler_level!r}")

    passed = not any(v.blocking for v in violations)
    return RuleResult(passed, violations, max(0, 100 - 10 * len(violations)) if passed else 0)
