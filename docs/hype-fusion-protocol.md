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

## 8. Slice selection (made after the freeze, before any ranking or scoring)

`slices` output, aggregates only (565 viewer clips with a VOD offset in the whole VOD):

| Block | Sum of views, top-10 clips | Clips with >=50 views |
|---|---:|---:|
| 0-3 h | 955 | 6 |
| 3-6 h | 252 | 1 |
| 6-9 h | 94 | 1 |
| 9-11.6 h | 221 | 1 |

Verdict slices by the rule: **0-3 h and 3-6 h**. Sanity slice: 2:00-5:00 (already prepared; overlaps both).
Note for the reader: Day 2's clips are weak everywhere (only block 0-3 has more than one clip with
>=50 views), so the >=50-view variant is usable on block 0-3 only.

## 9. Stop rule and clippable-fraction metric (added 2026-11-21 on Ahmad's instruction, before any scoring)

Ahmad capped the experiment to **this one round**. Nothing has been scored against viewer clips at
the time of this addendum; the rankings for the 0-3 h slice and the 2:00-5:00 sanity slice are
already saved (`ranking.json`), the 3-6 h ranking is made after this commit and before scoring.

**Stop rule.** If fused-Claude's pooled hit rate on the two verdict slices is below 50% on strict
or on overlap, or not above the pooled random 95th percentile, the experiment STOPS: report the
numbers, state the verdict, do not tune any detector, prompt or window budget, and do not start a
second round. (A pooled result of 50-60% is reported as "not reached", also without tuning.)

**Clippable fraction (secondary metric, reported for every arm, whatever the hit rate).** The share
of an arm's 15 windows per slice that are a *clippable moment*: self-contained and worth posting as
a short clip. It uses no viewer data at all. Method:

1. For each verdict slice and the sanity slice, take the 15 windows of chat-only, audio-only,
   transcript-only, fused-Claude and fused-RRF. Identical or heavily overlapping windows (>=50% overlap
   of the shorter one) are judged once. Items are shuffled with a fixed seed and shown WITHOUT the
   arm, signals, scores or viewer data: only the slice time, a chat sample (<= 4 lines) and the
   transcript text of the window (<= 1500 characters).
2. Judges: (a) the Claude Sonnet 5.5 session that ranked (judges the verdict slices only; NOT blind
   in the strict sense, because the same session chose the fused windows; disclosed); (b) an independent
   Codex judge (gpt-6.1-sol, medium) that never saw the ranking prompt or any outputs, all slices.
3. Frozen rubric, verbatim: *"Answer 1 (clippable) or 0. Clippable means: somewhere inside the window a
   viewer could cut a 20-60 second clip that (a) has a clear beat, i.e. a setup and a payoff such as a
   joke, a fail, a shock, a reveal, a big reaction or a tense escape; (b) makes sense to someone who has
   not watched the stream; (c) is not mainly chat reading, donation/sponsor talk, menu or loading
   time, idle planning, or the streamer talking over unrelated game audio. Borderline = 0."*
4. Reported per arm and slice: clippable windows / 15 from each judge, plus the share of windows both
   judges accept. Windows with no judgement count as 0.

The clippable fraction does not change the hit-rate verdict; it exists because viewer clips are a weak
and incomplete target on Day 2.

## 10. Results (scored 2026-11-21; one round, nothing tuned after scoring)

Viewer clips: the Day 2 list fetched 2026-11-20 (565 clips with a VOD offset), cached in `~/.autoclip/fusion/`.
Top-10 most-viewed clips per slice (hit counts out of 10). `rand` = mean / 95th percentile of 1000
random sets of the same window lengths. Cov = duration coverage of the arm's 15 windows.

| Slice | Arm | Cov | Strict | Overlap | Random strict (mean / p95) |
|---|---|---:|---:|---:|---|
| 0-3 h (verdict) | chat-only | 16% | 5 | 5 | 22% / 40% |
| | audio-only | 19% | 1 | 1 | 25% / 50% |
| | transcript-only | 14% | 3 | 4 | 20% / 40% |
| | **fused-Claude** | 17% | **7** | **7** | 23% / 50% |
| | fused-RRF (no LLM) | 16% | 6 | 6 | 24% / 50% |
| | pool-all (ceiling) | 51% | 8 | 9 | |
| 3-6 h (verdict) | chat-only | 13% | 2 | 2 | 19% / 40% |
| | audio-only | 18% | 0 | 0 | 25% / 50% |
| | transcript-only | 12% | 3 | 3 | 19% / 40% |
| | **fused-Claude** | 17% | **2** | **2** | 23% / 50% |
| | fused-RRF | 17% | 2 | 2 | 23% / 50% |
| | pool-all (ceiling) | 48% | 5 | 5 | |
| 2:00-5:00 (sanity, weak clips, overlaps both) | chat-only | 15% | 3 | 3 | 22% / 50% |
| | audio-only | 18% | 1 | 1 | 26% / 50% |
| | transcript-only | 14% | 6 | 6 | 21% / 40% |
| | fused-Claude | 17% | 4 | 4 | 24% / 50% |
| | fused-RRF | 17% | 5 | 5 | 24% / 50% |

**Pooled over the two verdict slices (20 clips, Wilson 95% interval):**

| Arm | Strict | Overlap | Pooled random strict (mean / p95) |
|---|---|---|---|
| chat-only | 7/20 = 35% [18, 57] | 7/20 = 35% | 21% / 40% |
| audio-only | 1/20 = 5% [1, 24] | 1/20 = 5% | 25% / 45% |
| transcript-only | 6/20 = 30% [15, 52] | 7/20 = 35% | 20% / 40% |
| **fused-Claude** | **9/20 = 45% [26, 66]** | **9/20 = 45% [26, 66]** | 23% / 45% |
| fused-RRF | 8/20 = 40% [22, 61] | 8/20 = 40% | 23% / 45% |

Variant with only clips of >=50 views: usable on 0-3 h only (n = 6): fused-Claude 5/6, chat 3/6,
transcript 2/6, audio 1/6; 3-6 h and 2:00-5:00 have n = 1 (not interpretable).

**Verdict: 60% was NOT reached.** Fused-Claude is 45% strict and 45% overlap on the verdict slices
(needs 60% on both), equal to the pooled random 95th percentile (45%), not above it. Under the stop rule
(section 9) the experiment stops here: no tuning, no second round. Fused is better than every single source on
the pooled count (45% vs chat 35%, transcript 30-35%, audio 5%), but the gain is 2 clips out of 20 and
well inside the interval. The fused result is carried by one slice (0-3 h: 7/10; 3-6 h: 2/10).
The ceiling is also informative: even a perfect ranker over the pooled candidates (pool-all, ~50% of the slice
covered) would reach only 13/20 = 65%.

**Clippable fraction** (rubric in section 9; windows of an arm judged clippable / distinct windows judged, ~15 per
slice; verdict slices pooled, 28-30 windows per arm). The Claude judge is a fresh Claude Sonnet 5.5 subagent that never
saw the rankings, scores or viewer clips (a deviation from section 9 that makes it MORE blind than planned,
since the ranking session itself did not judge); the second judge is Codex gpt-6.1-sol, medium. The Codex
judge's first run could not write its outputs (sandbox), so it was re-run on copies of the same item files placed in
the repo workspace (deleted afterwards); it saw nothing else.

| Arm | Claude judge | Codex judge |
|---|---:|---:|
| chat-only | 3 / 30 = 10% | 9 / 30 = 30% |
| audio-only | 4 / 29 = 14% | 10 / 29 = 34% |
| transcript-only | 2 / 30 = 7% | 9 / 30 = 30% |
| **fused-Claude** | **6 / 30 = 20%** | **15 / 30 = 50%** |
| fused-RRF | 4 / 28 = 14% | 9 / 28 = 32% |

Sanity slice (2:00-5:00): Claude judge chat 3, audio 1, transcript 3, fused-Claude 3, fused-RRF 5 (of 14-15);
Codex judge 8, 3, 6, 8, 7.
Both judges rank fused-Claude highest on the verdict slices, but the judges differ a lot in strictness
(Claude judge 7-20%, Codex judge 30-50%), the item counts are small, and the same counts for fused-Claude are
not independent of the ranker (it chose windows with a transcript it found clip-worthy, and the judges read
the same text). Treat it as a consistency check, not as proof of quality.

## 11. What was not verified / limits

- The ranker (a Claude session) also wrote the pipeline; its picks used transcript text and chat only. It
  knew the slice-level clip totals used for selection (disclosed) and, for slices 3-6 and 2:00-5:00, the
  windows overlap in hours 3:00-5:00 and the same moments were ranked twice (it remembered its earlier picks).
- 20 clips is small: the interval of the verdict number is 26-66%.
- Viewer clips on Day 2 are weak (565 clips, but only 7 of the 20 top-10 clips of 0-3 h and 3-6 h have 50 or more views).
- The audio detector found game dialogue and cutscene shouting as often as streamer reactions (1/20); no
  speaker separation was attempted (DSP only). The transcript detector relies on Whisper text without punctuation.
- The fused path is NOT wired into `clip stream`; `fusion.py`, `audio_hype.py`, `transcript_hype.py`
  and `scripts/hype_fusion_run.py` stay opt-in.
- Reproduce: `python scripts/hype_fusion_run.py candidates|judging|score|report ...` (work folder
  `~/.autoclip/fusion/`; rankings saved there as `ranking.json`; no credentials are stored in any of these files).
