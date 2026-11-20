# Hype fusion experiment: pre-registered protocol

Written 2026-11-20 and committed BEFORE any detector output was compared with viewer clips.
Code frozen at commit `e06fc80` (detectors, pooling, evaluation helpers, `scripts/hype_fusion_run.py`).
Question: does a fused detector (chat + independent audio + whole-transcript candidates, ranked by
Claude) reach a **60% hit rate** against viewer-made clips on a VOD no tuning has seen?

Anything changed after the first score is an *exploratory* result, reported separately and never
merged into the verdict.

## 1. Test data

- VOD: KreekCraft GTA 6 Day 2, Twitch `2933758895` (11.6 h). No detector default was tuned on it.
  Disclosure: an earlier sanity check (STATUS.md) looked at chat-only hits on the 2:00-5:00 slice,
  where the clips are weak (2-14 views). That slice is reported as a *sanity slice*, not in the verdict.
- Slices are 3 h. Selection rule (applied only after this protocol is committed): split the VOD into
  aligned blocks 0-3, 3-6, 6-9 and 9-end; fetch the viewer-clip list; compute, per block, only the sum
  of views of its top-10 clips and the number of clips with >=50 views (script command `slices`, which
  prints aggregates, never individual offsets). The two blocks with the highest top-10 view sum are
  the **verdict slices**. The existing 2:00-5:00 slice is the **sanity slice** (it overlaps blocks
  0-3/3-6 if those are chosen, so it is never pooled with them).
- Ground truth: the most-viewed viewer clips of the slice (clip `vod_offset` inside the slice).
  Primary set = top 10. Variant = top 10 among clips with >=50 views (n reported; if n < 5 it is shown
  but not used for the verdict). Matching exactly as `backend/autoclip/stream/hype_eval.py:hit_rate`:
  tolerance 30 s on each side of a window; **strict** = the clip's start point is inside a window,
  **overlap** = any part of the clip span touches a window.
- Viewer clips are never an input to any detector or to the ranker (no `viewer_clips` argument, no
  clip data in the ranking view). The experimenter (the ranking Claude session) learns only the
  per-block aggregates used for slice selection, not clip offsets, titles or views of single clips,
  before `ranking.json` is written.

## 2. Frozen detectors

All defaults are the dataclass defaults in the code at commit `e06fc80`.

| Source | Code | Frozen defaults (summary) |
|---|---|---|
| Chat | `pipeline/hype.py` `compute_hype(chat, duration_s=..., config=HypeConfig(top_n=...))` | `HypeConfig()` defaults: bin 10 s, rolling baseline 300 s, pre 30 s / post 10 s, merge gap 60 s, max window 150 s, min_z 1.5, w_rate 1, w_emote 2.0, w_unique 0.5, min_users 3, max_user_share 0.5. No loudness and no viewer-clip signal. This is the "chat-only" arm. |
| Audio | `pipeline/audio_hype.py` `compute_audio_hype(wav, duration_s=..., top_n=...)` | `AudioHypeConfig()` defaults: 16 kHz mono, 20 ms frames, 1 s hops, speech band 300-3400 Hz, robust (median/MAD) baseline 300 s, min_z 2.0, VAD gate (speech energy 3 dB over the local median, voice ratio >= 0.55, floor -70 dB), burst 1-6 s, long-loud (>10 s) and impulse penalties, 4-6 Hz modulation (laughter) weight 2.0, brightness weight 1.0, pre 30 s / post 10 s, merge gap 60 s, max window 150 s. DSP only, no model. |
| Transcript | `pipeline/transcript_hype.py` `compute_transcript_hype(transcript, duration_s=..., top_n=...)` | `TranscriptHypeConfig()` defaults: bin 10 s, speech-rate baseline 300 s, lexicon (no way, oh my god, let's go, holy, wtf, ...), repeated-word runs, laughter tokens, question and exclamation counts, speech-rate z-score, neighbour smoothing, min_score 2.0, pre 30 s / post 10 s, merge gap 60 s, max window 150 s. |

Transcripts: faster-whisper `large-v3-turbo`, int8_float32 on the GTX 1060, 20 min chunks (the
existing `transcribe()` path). Audio: Twitch audio-only rendition, converted to 16 kHz mono WAV
(the 2:00-5:00 slice uses the audio track of the full video already extracted by `clip stream`).
Chat: TwitchDownloaderCLI chat replay, shifted to slice time.

Window budget: **15 windows per 3 h slice per arm**, each window <= 150 s. Candidate pool: the top 20
peaks of each source (chat, audio, transcript). Pooling (`stream/fusion.py:pool_candidates`) merges
overlapping windows while the union stays <= 150 s; ids are assigned in time order.

## 3. Arms

1. **chat-only**: top 15 chat peaks (HEAD defaults of `hype.py`).
2. **audio-only**: top 15 audio peaks.
3. **transcript-only**: top 15 transcript peaks.
4. **fused-Claude (the verdict arm)**: the 15 candidate ids chosen by the ranking step below from the pool.
5. Secondary arm **fused-RRF** (no LLM): reciprocal-rank fusion with k = 10 of the per-source ranks of the pooled candidates, top 15.
6. Diagnostic only: **pool-all** (every pooled candidate), which bounds what any ranker could reach.

## 4. Ranking step (frozen prompt)

Done by the Claude Code session that builds the experiment (model: Claude Sonnet 5.5), one slice at
a time, from `ranking_view.md` of that slice, which lists for every candidate: slice time window,
per-source rank/score/reasons, a chat sample (<= 6 lines) and the transcript text of the window.
The ranker sees nothing else (no clip data, no VOD title beyond "KreekCraft GTA 6 stream", no
position-in-stream priors). Prompt, verbatim:

> You are picking the moments of a Twitch stream that viewers would most likely have clipped.
> Streamer: KreekCraft, playing GTA 6 (full-game stream). Below are candidate windows, each with:
> the time in the slice, which independent detectors flagged it (chat, audio, transcript), with their
> rank within their own list and reasons, a sample of chat messages, and the streamer's transcript
> for the window.
> Choose exactly 15 candidate ids, best first. Prefer, in this order:
> 1. a clear, self-contained moment: a big reaction (shock, laughter, shouting, disbelief), a funny
>    line, a fail or crash, a surprise, a reveal, a win;
> 2. the transcript showing what happened and how the streamer reacted, not just that it was loud;
> 3. agreement between independent detectors (a window flagged by several sources is stronger evidence,
>    but a window flagged by one source with a clearly clip-worthy transcript is acceptable);
> 4. variety: do not choose two candidates that show the same moment.
> Avoid: dead air, menus or loading, reading chat or donations, sponsor talk, planning or
> exposition without a payoff, repeated game audio without the streamer reacting.
> Use only the text given. Do not guess at information outside it. Output JSON:
> `{"ids": [15 ints], "why": {"<id>": "<<=12 words>"}}`.

Ties and uncertainty are resolved by the ranker's judgement, not by the signal rank. The output is
saved untouched as `ranking.json` per slice before any scoring; it is not edited afterwards.

## 5. Metrics and baselines

Per slice and arm: strict and overlap hit rate on the top-10 set (and the >=50-view variant),
the hit counts, and **duration coverage** (fraction of the slice covered by the union of the arm's
windows). **Random baseline** per arm: 1000 random sets of the same number and lengths of windows,
uniform start positions inside the slice (seed 20261120); mean and 95th percentile hit rate.
Pooled verdict numbers: hits / clips summed over the two verdict slices, with a Wilson 95% interval.

## 6. Verdict rule

"60% reached" requires **all** of: fused-Claude pooled strict >= 60% AND pooled overlap >= 60% on the
two verdict slices (top-10 set); fused-Claude pooled strict above the pooled random 95th percentile.
If only the overlap number clears 60% this is reported as "partially" and not as a pass. With ~20
clips a Wilson interval is wide (about +/-20 percentage points); the report states this and does not
claim more than the numbers show. The sanity slice and the >=50-view variants are reported but do
not change the verdict.

## 7. Known limits (stated up front)

Viewer clips are an incomplete, noisy positive set (many are 2-30 view clips). Chat on this stream
is sparse (0.4-0.8 msg/s). Day 2 is one stream of one streamer. The ranker is a Claude session that
also designed the pipeline; it never saw clip data, but the experimenter chose the slices using clip
totals (disclosed). The audio and transcript detectors are untuned designs; one Codex benchmark run
printed the audio top-15 times on the 2:00-5:00 slice for timing only (no clip data was available
to it).

## 8. Results

(appended after scoring)
