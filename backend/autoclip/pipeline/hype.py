"""Find collective reactions early enough to retain the event that caused them."""

from __future__ import annotations

import math
import re
import subprocess
from bisect import bisect_left, bisect_right
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

from autoclip.stream.chat import ChatLog, ChatMessage

from .ffmpeg import FFmpegError, ffmpeg_path

# Patterns are bounded as whole tokens below: "LUL" must not also match "OMEGALUL".
# Strong explicit clipping requests outweigh casual exclamations.
HYPE_PHRASES: dict[str, tuple[str, float]] = {
    "KEKW": (r"kekw", 1.5),
    "LUL": (r"lul", 1.0),
    "LULW": (r"lulw", 1.2),
    "OMEGALUL": (r"omegalul", 1.5),
    "ICANT": (r"icant", 1.2),
    "???": (r"\?{3,}", 1.0),
    "POGGERS": (r"poggers", 1.5),
    "Pog": (r"pog", 1.5),
    "PogChamp": (r"pogchamp", 1.5),
    "CLIP IT": (r"clip\s+it", 2.5),
    "clip that": (r"clip\s+that", 2.5),
    "no way": (r"no\s+way", 1.5),
    "W": (r"w+", 0.7),
    "L": (r"l+", 0.7),
    "LETS GO": (r"let'?s\s+go+", 1.5),
    "LETSGOOO": (r"letsgo+", 1.5),
    "OMG": (r"omg", 1.0),
    "WTF": (r"wtf", 1.2),
    "HOLY": (r"holy", 1.0),
    "BRO": (r"bro", 0.5),
}
_LABELS = list(HYPE_PHRASES)
_HYPE_RE = re.compile(
    r"(?<!\w)(?:"
    + "|".join(rf"(?P<p{i}>{pattern})" for i, (pattern, _) in enumerate(HYPE_PHRASES.values()))
    + r")(?!\w)",
    re.IGNORECASE,
)


@dataclass
class HypeConfig:
    """Keep timing and signal weights editable for different chat communities."""

    bin_s: float = 5.0
    rolling_window_s: float = 300.0
    pre_s: float = 30.0
    post_s: float = 10.0
    merge_gap_s: float = 60.0
    #: Merging chains of nearby peaks stops once a window would exceed this length, so a
    #: busy stretch becomes several clippable windows rather than one 8-minute blob.
    max_window_s: float = 150.0
    top_n: int = 15
    min_z: float = 1.5
    w_rate: float = 1.0
    w_emote: float = 0.8
    w_unique: float = 0.5
    w_loud: float = 0.4
    w_viewer_clip: float = 1.0

    def __post_init__(self) -> None:
        for name in ("bin_s", "rolling_window_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in (
            "pre_s",
            "post_s",
            "merge_gap_s",
            "max_window_s",
            "min_z",
            "w_rate",
            "w_emote",
            "w_unique",
            "w_loud",
            "w_viewer_clip",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not isinstance(self.top_n, int) or self.top_n < 0:
            raise ValueError("top_n must be a nonnegative integer")


@dataclass
class HypePeak:
    """Carry both the reaction time and the earlier context needed by the editor."""

    t: float
    score: float
    window_start: float
    window_end: float
    reasons: list[str]
    sample_messages: list[str]


@dataclass
class _Bin:
    users: Counter[str] = field(default_factory=Counter)
    emote_users: Counter[str] = field(default_factory=Counter)
    phrases: Counter[str] = field(default_factory=Counter)


def _phrases(text: str) -> Counter[str]:
    return Counter(_LABELS[int(m.lastgroup[1:])] for m in _HYPE_RE.finditer(text))


def _baseline(
    values: list[float | None], window: int, *, floor: float, poisson: bool = False
) -> tuple[list[float], list[float]]:
    """Use rolling sums so a long VOD does not rescan five minutes for every bin."""
    history: deque[float | None] = deque()
    total = squares = 0.0
    count = 0
    zs: list[float] = []
    means: list[float] = []
    for value in values:
        mean = total / count if count else 0.0
        variance = max(0.0, squares / count - mean * mean) if count else 0.0
        sd = max(math.sqrt(variance), math.sqrt(max(mean, floor)) if poisson else floor)
        zs.append(max(0.0, (value - mean) / sd) if count and value is not None else 0.0)
        means.append(mean)
        history.append(value)
        if value is not None:
            total += value
            squares += value * value
            count += 1
        if len(history) > window:
            old = history.popleft()
            if old is not None:
                total -= old
                squares -= old * old
                count -= 1
    return zs, means


def compute_hype(
    chat: ChatLog,
    *,
    loudness: list[tuple[float, float]] | None = None,
    viewer_clips: list[float] | None = None,
    duration_s: float | None = None,
    config: HypeConfig | None = None,
) -> list[HypePeak]:
    """Rank collective reactions, preserving the lead-in before delayed chat peaks.

    Rate is measured in messages/second with at most three messages per user/bin.
    Its z-score equals the count z-score (mean and deviation scale by bin size).
    Three distinct named users and no user sending over half the bin's messages
    are required for chat signals. Audio and viewer clips can supply evidence
    independently when replay chat is missing.
    """
    cfg = config or HypeConfig()
    duration = duration_s if duration_s is not None else (chat.duration_s or None)
    if duration is not None and (not math.isfinite(duration) or duration < 0):
        raise ValueError("duration_s must be finite and nonnegative")

    def valid(t: float) -> bool:
        return math.isfinite(t) and t >= 0 and (duration is None or t < duration)

    messages = sorted((m for m in chat.messages if valid(m.t)), key=lambda m: m.t)
    audio = [(t, db) for t, db in loudness or [] if valid(t) and math.isfinite(db)]
    clips = [t for t in viewer_clips or [] if valid(t)]
    times = [m.t for m in messages] + [t for t, _ in audio] + clips
    if not times or cfg.top_n == 0:
        return []
    size = (
        max(1, math.ceil(duration / cfg.bin_s))
        if duration is not None
        else (int(max(times) / cfg.bin_s) + 1)
    )
    bins = [_Bin() for _ in range(size)]
    for message in messages:
        bucket = bins[int(message.t / cfg.bin_s)]
        # Missing identities cannot establish independent participation.
        user = message.user.strip().casefold()
        if not user:
            continue
        bucket.users[user] += 1
        # Emote fragments usually duplicate the body; the union avoids counting twice.
        phrases = _phrases(message.text)
        if message.emotes:
            phrases |= _phrases(" ".join(message.emotes))
        if not phrases:
            continue
        bucket.phrases.update(phrases)
        weight = sum(HYPE_PHRASES[label][1] * count for label, count in phrases.items())
        bucket.emote_users[user] += weight

    window = max(1, math.ceil(cfg.rolling_window_s / cfg.bin_s))
    rates = [float(sum(min(n, 3) for n in b.users.values())) for b in bins]
    rate_z, rate_mean = _baseline(rates, window, floor=1.0, poisson=True)
    unique_z, _ = _baseline([float(len(b.users)) for b in bins], window, floor=1.0, poisson=True)
    audio_bins: dict[int, list[float]] = {}
    for t, db in audio:
        audio_bins.setdefault(int(t / cfg.bin_s), []).append(db)
    levels: list[float | None] = [None] * size
    for i, dbs in audio_bins.items():
        # Average energy rather than dB if callers supply multiple samples per bin.
        levels[i] = 10 * math.log10(
            sum(10 ** (max(-120, min(db, 100)) / 10) for db in dbs) / len(dbs)
        )
    loud_z, _ = _baseline(levels, window, floor=3.0)

    # Difference intervals avoid comparing every viewer clip with every chat bin.
    clip_delta = [0] * (size + 1)
    for t in clips:
        start = max(0, math.ceil((t - 15) / cfg.bin_s - 0.5))
        end = min(size - 1, math.floor((t + 15) / cfg.bin_s - 0.5))
        if start <= end:
            clip_delta[start] += 1
            clip_delta[end + 1] -= 1
    scores: list[float] = []
    reasons: list[list[str]] = []
    clip_count = 0
    for i, bucket in enumerate(bins):
        collective = (
            len(bucket.users) >= 3 and max(bucket.users.values()) <= bucket.users.total() / 2
        )
        emote = sum(min(n, 3.0) for n in bucket.emote_users.values()) / math.sqrt(max(rates[i], 4))
        clip_count += clip_delta[i]
        score = (
            (cfg.w_rate * rate_z[i] + cfg.w_unique * unique_z[i] + cfg.w_emote * emote) * collective
            + cfg.w_loud * loud_z[i]
            + cfg.w_viewer_clip * 3.0 * min(clip_count, 3)
        )
        why = []
        if collective and rate_z[i] > 0 and cfg.w_rate:
            why.append(f"chat {rates[i] / max(rate_mean[i], 1):.1f}x baseline")
        if collective and cfg.w_emote:
            why.extend(f"{label} x{n}" for label, n in bucket.phrases.most_common(3))
        if collective and unique_z[i] > 0 and cfg.w_unique:
            why.append(f"{len(bucket.users)} unique chatters (+{unique_z[i]:.1f} sd)")
        if loud_z[i] > 0 and cfg.w_loud:
            why.append(f"loud +{loud_z[i]:.1f} sd")
        if clip_count and cfg.w_viewer_clip:
            why.append(f"{clip_count} viewer clips nearby")
        scores.append(score)
        reasons.append(why)

    candidates: list[HypePeak] = []
    for i, score in enumerate(scores):
        # Strict on the left picks the first bin of a plateau deterministically.
        if score <= 0 or score < cfg.min_z:
            continue
        if i and score <= scores[i - 1]:
            continue
        if i + 1 < size and score < scores[i + 1]:
            continue
        t = (i + 0.5) * cfg.bin_s
        if duration is not None:
            t = min(t, duration)
        candidates.append(
            HypePeak(
                t,
                score,
                max(0.0, t - cfg.pre_s),
                min(t + cfg.post_s, duration) if duration is not None else t + cfg.post_s,
                reasons[i],
                [],
            )
        )

    merged: list[HypePeak] = []
    for peak in candidates:
        if (
            merged
            and (
                peak.window_start <= merged[-1].window_end
                or peak.window_start - merged[-1].window_end < cfg.merge_gap_s
            )
            and max(merged[-1].window_end, peak.window_end) - merged[-1].window_start
            <= cfg.max_window_s
        ):
            previous = merged[-1]
            best = peak if peak.score > previous.score else previous
            merged[-1] = HypePeak(
                best.t,
                best.score,
                previous.window_start,
                max(previous.window_end, peak.window_end),
                best.reasons,
                [],
            )
        else:
            merged.append(peak)
    selected = sorted(merged, key=lambda p: (-p.score, p.t))[: cfg.top_n]
    message_times = [m.t for m in messages]
    for peak in selected:
        start = bisect_left(message_times, peak.window_start)
        end = bisect_right(message_times, peak.window_end)
        peak.sample_messages = _samples(messages, start, end)
    return selected


def _samples(messages: list[ChatMessage], start: int, end: int) -> list[str]:
    """Prefer distinct reacting users so copypasta cannot consume all eight lines."""
    samples: list[str] = []
    users: set[str] = set()
    for reacting in (True, False):
        for i in range(start, end):
            message = messages[i]
            user = message.user.casefold()
            if user in users or not message.text.strip():
                continue
            if reacting and not (_HYPE_RE.search(message.text) or message.emotes):
                continue
            samples.append(f"{message.user}: {message.text}")
            users.add(user)
            if len(samples) == 8:
                return samples
    return samples


def loudness_series(media: Path, *, bin_s: float = 5.0) -> list[tuple[float, float]]:
    """Stream bin RMS metadata, keeping RAM bounded even for multi-hour media.

    Resampling before astats bounds its frame buffer. Silence is represented by
    -120 dB rather than negative infinity so downstream z-scores remain finite.
    Missing audio yields []; decoding failures raise FFmpegError with a short tail.
    """
    if not math.isfinite(bin_s) or bin_s <= 0:
        raise ValueError("bin_s must be finite and positive")
    samples = max(1, round(8000 * bin_s))
    command = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(media),
        "-map",
        "0:a:0?",
        "-vn",
        "-af",
        f"aresample=8000,asetpts=PTS-STARTPTS,asetnsamples=n={samples}:p=0,"
        "astats=metadata=1:reset=1,"
        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
        "-f",
        "null",
        "-",
    ]
    result: list[tuple[float, float]] = []
    tail: deque[str] = deque(maxlen=20)
    timestamp = 0.0
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                tail.append(line)
                if match := re.search(r"pts_time:([\d.eE+-]+)", line):
                    timestamp = float(match.group(1))
                elif line.startswith("lavfi.astats.Overall.RMS_level="):
                    db = float(line.partition("=")[2])
                    result.append((timestamp, max(-120.0, db) if math.isfinite(db) else -120.0))
            proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        if proc.returncode:
            error = "".join(tail)
            if "does not contain any stream" in error:
                return []
            raise FFmpegError("Loudness analysis failed.", command=command, stderr=error)
    return result


def evaluate_peaks(
    peaks: list[HypePeak],
    truth_times: list[float],
    *,
    top_k: int = 10,
    tolerance_s: float = 30.0,
) -> float:
    """Measure precision among available top-k windows without penalising short lists.

    Each prediction counts once if any truth time lies inside its expanded window;
    this measures precision, not recall or one-to-one event matching.
    """
    if not math.isfinite(tolerance_s) or tolerance_s < 0:
        raise ValueError("tolerance_s must be finite and nonnegative")
    selected = sorted(peaks, key=lambda p: (-p.score, p.t))[: max(0, top_k)]
    if not selected:
        return 0.0
    truth = sorted(t for t in truth_times if math.isfinite(t))
    hits = 0
    for peak in selected:
        i = bisect_left(truth, peak.window_start - tolerance_s)
        hits += i < len(truth) and truth[i] <= peak.window_end + tolerance_s
    return hits / len(selected)
