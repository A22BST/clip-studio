"""Read existing prepared VOD data; write only the explicitly selected local report.

Exploratory diagnostics, not the frozen hype-fusion benchmark. No downloads,
transcription, model calls, or writes to the input data directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
from autoclip.pipeline.audio_hype import AudioHypeConfig, _robust_baseline, audio_features
from autoclip.pipeline.crashout import crashout_from_features, overlap_fraction
from autoclip.pipeline.transcript import Transcript
from autoclip.pipeline.transcript_hype import _LAUGH, _token

TARGETS = {
    "2933758895": ("Day 2", 7200.0, (7661.0, 7705.0), "jet-ski"),
    "2934981732": ("Day 3", 6000.0, None, ""),
    "2936183180": ("Day 4", 0.0, (928.0, 957.0), "tiger"),
}


def prepared(root, vod, offset):
    """Match work metadata to stream duration, deriving slice offset explicitly."""
    streams = []
    for path in sorted((root / "streams").glob("*/stream.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        if str(meta.get("vod_id")) == vod and float(meta.get("trim_start_s", 0)) == offset:
            streams.append((path.parent, meta))
    for path in sorted((root / "work").glob("*/candidates.json")):
        if "-cmp" in path.parent.name:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data.get("stream", {}).get("vod_id")) != vod:
            continue
        duration = float(data["stream"]["duration_s"])
        match = next((s for s in streams if abs(float(s[1]["duration_s"]) - duration) < 2), None)
        if match:
            yield path.parent, match[0], duration, data


def legacy_diagnostics(f, transcript):
    """Frozen first-pass gates, evaluated on its original one-second hops."""
    t = f.t
    base, scale = _robust_baseline(f.speech_db, 120)
    rise = f.speech_db - base
    z = np.maximum(0, rise / np.maximum(scale, 3))
    speech = (t >= 2) & (f.speech_db > -55) & (f.voice_ratio >= 0.45) & (f.occupancy >= 0.25)
    bins = np.zeros(math.ceil(f.duration_s))
    swear_bins, laugh_bins = bins.copy(), bins.copy()
    for word in transcript.words:
        if not math.isfinite(word.start) or not 0 <= word.start < f.duration_s:
            continue
        j = int(word.start)
        bins[j] += 1
        tok = _token(word.text)
        swear_bins[j] += tok in {"fuck", "fucking", "shit", "bullshit", "damn", "bitch", "wtf"}
        laugh_bins[j] += bool(_LAUGH.match(tok))

    def counts(values, radius):
        prefix = np.r_[0, np.cumsum(values)]
        lo = np.clip(np.floor(t - radius).astype(int), 0, len(values))
        hi = np.clip(np.ceil(t + radius).astype(int), 0, len(values))
        return prefix[hi] - prefix[lo]

    nearby = counts(bins, 12) > 0
    words_present = bins[np.floor(t).astype(int)] > 0
    ratio = np.zeros(len(t))
    for i, value in enumerate(f.pitch_hz):
        hist = f.pitch_hz[max(0, i - 120) : i]
        hist = hist[np.isfinite(hist) & (hist > 0)]
        if value > 0 and len(hist):
            ratio[i] = value / np.median(hist)
    pitch = speech & (ratio >= 1.4)
    loud = speech & (rise >= 5) & (z >= 1.5)

    def lengths(mask):
        out = np.zeros(len(t))
        for lo, hi in np.flatnonzero(np.diff(np.r_[False, mask, False])).reshape(-1, 2):
            out[lo:hi] = hi - lo
        return out

    plen = lengths(pitch)
    eligible = nearby & ((loud & (lengths(loud) <= 10)) | (pitch & (plen >= 2) & (plen <= 10)))
    bright, _ = _robust_baseline(f.centroid, 120)
    brightness_jump = f.centroid > np.maximum(bright, 300) * 1.3
    laugh = ((f.modulation >= 0.20) & (f.flux > 0)) | (counts(laugh_bins, 2) > 0)
    rage = loud & (counts(bins, 2) / 4 >= 3) & (counts(swear_bins, 2) >= 2)
    score = np.minimum(z, 8) + 0.5 * np.minimum(
        np.maximum(np.r_[0, np.diff(f.speech_db)], 0) / 6, 3
    )
    score += brightness_jump + 2 * (ratio >= 1.4) + 1.5 * laugh + 2 * rage
    eligible &= score >= 2
    return {
        "rise": rise,
        "z": z,
        "ratio": ratio,
        "speech": speech,
        "nearby": nearby,
        "words_present": words_present,
        "pitch_seconds": plen,
        "score": score,
        "eligible": eligible,
    }


def legacy_windows(f, diagnostic):
    """Reconstruct original context merging and 10/hour cap for attribution."""
    eligible, score = diagnostic["eligible"], diagnostic["score"]
    merged = []
    for i in np.flatnonzero(eligible):
        if (i and eligible[i - 1] and score[i] <= score[i - 1]) or (
            i + 1 < len(f.t) and eligible[i + 1] and score[i] < score[i + 1]
        ):
            continue
        start = max(0.0, min(float(f.t[i]) - 12, f.duration_s - 20))
        end = min(f.duration_s, max(float(f.t[i]) + 10, start + 20))
        p = {
            "peak_t": float(f.t[i]),
            "hype_score": round(float(score[i]), 2),
            "window_start_s": start,
            "window_end_s": end,
        }
        if (
            merged
            and start <= merged[-1]["window_end_s"] + 4
            and end - merged[-1]["window_start_s"] <= 60
        ):
            prev = merged[-1]
            best = dict(p if p["hype_score"] > prev["hype_score"] else prev)
            best["window_start_s"] = prev["window_start_s"]
            best["window_end_s"] = max(prev["window_end_s"], end)
            merged[-1] = best
        else:
            merged.append(p)
    chosen, hours = [], {}
    for p in sorted(merged, key=lambda p: (-p["hype_score"], p["peak_t"])):
        hour = int(p["peak_t"] // 3600)
        budget = min(10, max(1, math.ceil(10 * min(3600, f.duration_s - hour * 3600) / 3600)))
        if hours.get(hour, 0) >= budget:
            continue
        hours[hour] = hours.get(hour, 0) + 1
        chosen.append(p)
    return merged, chosen


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return f"{stat.st_size} bytes; mtime {stat.st_mtime_ns}; SHA256 `{digest.hexdigest()}`"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("D:/autoclip"))
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).parent / "out/crashout_eval.md"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(args.root.resolve()):
        parser.error("report must not be written under the read-only input root")
    lines = [
        "# Crash-out evaluation",
        "",
        "Exploratory defaults; no ground-truth tuning. Audio and transcript times are slice-local; "
        "tables below use source seconds.",
        "Coverage = best single candidate intersection / annotated moment duration, "
        "with a 50% threshold (union also reported). Chat overlap = intersection / "
        "shorter window >= 50%.",
        "All selected existing candidates have chat samples (Day 2/3/4: "
        "15/15/14); overlap is against these chat-backed windows, which may "
        "also contain loudness or viewer-clip evidence.",
        "Mixed audio and undiarized transcripts cannot establish streamer identity. "
        "Nearby words (within 12 s) suppress speech-free stretches; game dialogue can still pass.",
        "New defaults: 120 s speech-conditioned median/MAD z-score; pitch "
        ">=20% for 0.5-10 s OR loudness z>=1.5 OR a token-backed speech-rate"
        " burst. Bounded joint scoring; 15 candidates per hour. No "
        "timestamp-specific rules.",
        "",
        "| VOD | Voice candidates (per hour) | Chat-backed overlap fraction "
        "| NEW | Coverage | DSP wall time |",
        "|---|---:|---:|---:|---|---:|",
    ]
    details = [
        "",
        "## Diagnosis and limitations",
        "",
        "Jet-ski: nearby words pass throughout. Most hops fail the >=5 dB "
        "and >=1.5 robust-z loudness conjunction; at 7674.5 s rise=4.98 dB, "
        "z=1.05, F0=1.97x, but pitch lasts only 1 s and fails the old 2 s "
        "minimum. At 7701.5-7703.5 s pitch DOES qualify before ranking. Thus"
        " the old hourly ranking cap also removes a valid proposal near this"
        " annotation. Dedupe is not the cause: coverage is measured on voice"
        " candidates before dedupe.",
        "Tiger: nearby words pass. At 929.5 s loudness rises 21.68 dB but "
        "z=1.37 misses 1.5; F0=2.03x lasts 1 s. At 932.5 s F0=2.68x is again"
        " isolated. The old 2 s pitch minimum and inflated mixed "
        "silence/voice baseline scale suppress these short reactions before "
        "the cap. Dedupe is not involved.",
        "The first generalized revision (same 20% pitch, speech-conditioned "
        "120 s z baseline, 0.5 s hop) produced Day 2 45 (15.00/h), overlap "
        "11/45, coverage 0%; Day 3 35 (15.00/h), overlap 4/35; Day 4 9 "
        "(15.28/h), overlap 7/9, coverage 38.8%. The final revision fixes a "
        "general context-merging defect: merge events within 4 s, rather "
        "than chaining overlapping context windows into arbitrary 60 s "
        "tiles. It also scores normalized onset sharpness and floors "
        "partial-hour budgets. No annotation timestamps enter detection or "
        "ranking; these changes were not selected by a threshold sweep.",
        "",
        "## Earlier inconsistent-input rerun",
        "",
        "Recovered session "
        "rollout-2026-11-21T23-19-08-01a20031-1a8b-7eb1-91ed-7e1f04b942f3.jsonl,"
        " ordinal 266 (22:30:06Z): one Day 2 candidate (source 7200-7227.5, "
        "peak 7203.5), DSP 2.16 s; Day 3 and Day 4 reported missing prepared"
        " metadata. Ordinal 275 then found the expected files (Day 2/3/4 "
        "audio sizes 345599958/268800124/67840968 bytes) and Day 2 stream "
        "offset 7200, duration 10800.01. Ordinal 318 subsequently read the "
        "same paths, found one Day 3 and one Day 4 job, and decoded Day 2 to"
        " 10799 hops / 10799.99 s. The original note is in parent session "
        "23-18-17, ordinal 514.",
        "The bad run did not record decoded duration or input hashes. There "
        "is no evidence proving that prepared inputs changed, a slice offset"
        " differed, or different files were selected. Root cause remains "
        "undetermined; incomplete decoding is a hypothesis, not an "
        "established explanation. This report records exact selected files, "
        "metadata, sizes, timestamps and SHA256 hashes and rejects "
        "decoded-duration mismatches. Paths embedded in stream.json refer to"
        " an earlier C: storage location; resolution deliberately uses the "
        "existing D: prepared directories.",
    ]
    for vod, (label, offset, target, name) in TARGETS.items():
        jobs = list(prepared(args.root, vod, offset))
        if not jobs:
            lines.append(
                f"| {label} {vod} | missing prepared metadata for offset {offset:g} "
                "| - | - | not evaluated | - |"
            )
            continue
        # One canonical prepared job per VOD/slice; comparison job copies excluded.
        work, stream, duration, data = jobs[0]
        audio = next((p for p in (work / "audio.wav", stream / "audio.wav") if p.exists()), None)
        transcript = next(
            (p for p in (work / "transcript.json", stream / "transcript.json") if p.exists()), None
        )
        if audio is None or transcript is None:
            missing = []
            if audio is None:
                missing.append(f"audio.wav absent in {work} and {stream}")
            if transcript is None:
                missing.append(f"transcript.json absent in {work} and {stream}")
            lines.append(f"| {label} {vod} | {'; '.join(missing)} | - | - | not evaluated | - |")
            continue
        started = time.perf_counter()
        features = audio_features(audio, config=AudioHypeConfig(hop_s=0.5), include_pitch=True)
        if abs(features.duration_s - duration) > 2:
            lines.append(
                f"| {label} {vod} | decoded duration mismatch "
                f"({features.duration_s:.2f} vs metadata {duration:.2f}s) "
                "| - | - | not evaluated | - |"
            )
            continue
        tr = Transcript.load(transcript)
        diag = {}
        voice = crashout_from_features(features, tr, diagnostics=diag)
        elapsed = time.perf_counter() - started
        old = data.get("candidates", [])
        overlap = sum(any(overlap_fraction(v, c) >= 0.5 for c in old) for v in voice)
        coverage = "no annotation"
        if target:
            spans = sorted(
                (
                    max(target[0], v["window_start_s"] + offset),
                    min(target[1], v["window_end_s"] + offset),
                )
                for v in voice
            )
            total, end = 0.0, target[0]
            for lo, hi in spans:
                if hi > max(lo, end):
                    total += hi - max(lo, end)
                    end = hi
            fraction = max((max(0.0, hi - lo) for lo, hi in spans), default=0.0) / (
                target[1] - target[0]
            )
            union = total / (target[1] - target[0])
            coverage = (
                f"{name}: {'YES' if fraction >= 0.5 else 'NO'} "
                f"(best {fraction:.1%}, union {union:.1%}, "
                f"target {target[0]:g}-{target[1]:g})"
            )
        lines.append(
            f"| {label} {vod} | {len(voice)} ({len(voice) / (duration / 3600):.2f}/h) | "
            f"{overlap}/{len(voice)} ({overlap / max(1, len(voice)):.1%}) | "
            f"{len(voice) - overlap} "
            f"| {coverage} | {elapsed:.2f} s / {duration / 3600:.2f} h |"
        )
        details += [
            "",
            f"## {label}: {vod}",
            "",
            f"Audio: `{audio}`; transcript: `{transcript}`; "
            f"existing candidates: `{work / 'candidates.json'}`.",
            f"Source offset: {offset:g} s. "
            f"Detector runtime: {elapsed / (duration / 3600):.2f} seconds per audio hour.",
            "",
        ]
        for path in (audio, transcript, work / "candidates.json", stream / "stream.json"):
            details.append(f"Input `{path}`: {fingerprint(path)}.")
        if target:
            legacy = audio_features(audio, include_pitch=True)
            old_diag = legacy_diagnostics(legacy, tr)
            before_cap, after_cap = legacy_windows(legacy, old_diag)
            old_touching = [
                p
                for p in before_cap
                if p["window_start_s"] + offset < target[1]
                and p["window_end_s"] + offset > target[0]
            ]
            old_kept = sum(p in after_cap for p in old_touching)
            details += [
                "",
                f"Reconstructed first-pass output: {len(after_cap)} candidates; "
                f"{len(old_touching)} merged proposals touch this annotation before "
                f"the hourly cap, {old_kept} survive it.",
            ]
            details += [
                "",
                "### First-pass raw per-second diagnosis",
                "",
                "F0 is ratio to preceding voiced 120 s median; 0 means no "
                "F0. Word present means a recognized word starts in that "
                "second. The audio speech gate checks level/ratio/occupancy;"
                " nearby uses the exact original floor/ceil 12 s histogram "
                "gate. Old eligible includes the original score >=2 and "
                "precedes ranking/cap and dedupe. All decoded feature arrays"
                " were finite.",
                "",
                "| Source second | Rise dB | Robust z | F0 ratio | Word "
                "present | Audio speech gate | Nearby speech gate | Pitch "
                "run s | Old score | Old eligible | New eligible in second |",
                "|---:|---:|---:|---:|---|---|---|---:|---:|---|---|",
            ]
            for i in np.flatnonzero(
                (legacy.t + offset >= target[0] - 15) & (legacy.t + offset <= target[1] + 15)
            ):
                newer = (features.t >= legacy.t[i] - 0.5) & (features.t < legacy.t[i] + 0.5)
                details.append(
                    f"| {legacy.t[i] + offset:.1f} | {old_diag['rise'][i]:.2f} | "
                    f"{old_diag['z'][i]:.2f} | {old_diag['ratio'][i]:.2f} | "
                    f"{bool(old_diag['words_present'][i])} | "
                    f"{bool(old_diag['speech'][i])} | {bool(old_diag['nearby'][i])} | "
                    f"{old_diag['pitch_seconds'][i]:.0f} | {old_diag['score'][i]:.2f} | "
                    f"{bool(old_diag['eligible'][i])} | "
                    f"{bool(diag['eligible'][newer].any())} |"
                )
            proposals = [
                v
                for v in diag["proposals"]
                if v["window_start_s"] + offset < target[1]
                and v["window_end_s"] + offset > target[0]
            ]
            details += [
                "",
                "Uncapped proposals touching the annotation: "
                + "; ".join(
                    f"{v['window_start_s'] + offset:.2f}-{v['window_end_s'] + offset:.2f} "
                    f"(score {v['hype_score']})"
                    for v in proposals
                )
                + ". These are diagnostic only; reported coverage uses capped output.",
            ]
            details += [
                "",
                "### New ranked candidates",
                "",
                "| Rank | Source window | Source peak | Score | NEW | Signals |",
                "|---:|---|---:|---:|---|---|",
            ]
        if not target:
            details += [
                "",
                "| Rank | Source window | Source peak | Score | NEW | Signals |",
                "|---:|---|---:|---:|---|---|",
            ]
        for v in voice:
            new = not any(overlap_fraction(v, c) >= 0.5 for c in old)
            details.append(
                f"| {v['rank']} | {v['window_start_s'] + offset:.1f}-"
                f"{v['window_end_s'] + offset:.1f} "
                f"| {v['peak_t'] + offset:.1f} | {v['hype_score']} "
                f"| {'yes' if new else 'no'} | {', '.join(v['signals'])} |"
            )
    report = "\n".join(lines + details) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
