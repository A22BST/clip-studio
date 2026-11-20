---
name: clip
description: Pick the clips for a streamer VOD prepared by `clip stream`. Reads candidates.json (chat-hype windows + transcript + chat sample), chooses 5-10 clips with hooks, titles, captions, hashtags, a layout and a spoiler level, writes highlights.json, then re-runs `clip stream` to render. Use when the user says /clip, "pick the clips", or a `clip stream` run says it is waiting for clip selection.
model: sonnet
argument-hint: "<job-id> [--campaign name]"
---

# /clip: choose clips for a stream job

No API key is involved: YOU (Claude in this session) are the selector. The pipeline already found the
hot moments from chat; your job is to turn them into good, safe, on-brief clips.

## 0. Preconditions
- Run from the repo root (`clip-studio`), venv active (`.venv\Scripts\activate`).
- `$ARGUMENTS` is the job id. If empty, use the newest folder in `%USERPROFILE%\.autoclip\work\` that has
  `candidates.json` and no `highlights.json`.
- Read `%USERPROFILE%\.autoclip\work\<job>\candidates.json`. It holds `limits` (campaign min/max seconds, required
  hashtags/mentions, spoiler policy) and ~15 `candidates`, each with `window_start_s/end_s`, `hype_reasons`,
  `chat_sample` (real chat lines at the peak) and `transcript` rendered as `[wordIndex]word`.
- Also read `campaigns/<campaign>.yaml` if you need the full rules (banned words, notes).

## 1. Decide per candidate (work through ALL of them)
1. Read the transcript and chat sample. Chat reacts 5-20 s AFTER the event, so the clip must START before the event
   with a little setup, and end on the payoff/reaction, not mid-sentence.
2. Choose `start_word_index` and `end_word_index` by copying the `[index]` numbers from the transcript (never
   compute indexes). Aim for `limits.min_duration_s`..`limits.max_duration_s` (about 20-60 s works best). Start on
   a sentence start where possible. The pipeline snaps to sentences/silence afterwards.
3. Skip a candidate when: nothing actually happens, it is only chat spam, it needs context nobody has, or it is
   boring dead air. Quality over count: 5-10 clips total, best first. Never invent moments the transcript does not support.
4. Overlapping candidates: keep the better one.

## 2. Spoiler level (keep it LIGHT: three levels only)
Set `spoiler_level` per clip:
- `none`: normal gameplay/talk/funny moment. Nothing changes.
- `reaction-to-spoiler`: the clip is about the streamer's REACTION to a GTA 6 story moment (mission twist, death,
  reveal, ending). KEEP it. Set `layout: "reaction"` and, if the reveal shows on screen in a known second range,
  add `blur_word_ranges: [[firstWordIndex, lastWordIndex]]`: the `[index]` numbers of the words spoken
  while the reveal is on screen (word indexes, never seconds: the pipeline converts them to exact times,
  so they stay right when the cut is refined). Cover only the reveal moment. The `hook` and `title` MUST be spoiler-free:
  "his reaction to THAT mission 😭", never the plot point. Do not name characters/events that are the spoiler.
- `raw-cinematic`: the window is mostly cutscene/ending/leaked footage with little streamer reaction (the
  transcript is cutscene dialogue, the streamer is silent, chat is reacting to the footage itself). REJECT:
  still list it with this level so the pipeline records the rejection, but do not expect it to render.
If the campaign's own notes carry a stricter spoiler rule, that rule wins (set the level honestly; the rules
engine blocks it under `strict`).

## 3. Hook, title, caption, hashtags
- `hook`: <= 8 words, shown for 2 s at the top, creates curiosity or states the payoff without spoilers
  ("He did NOT expect this", "chat lost it at 0:12"). No clickbait that the clip does not deliver.
- `title`: <= `max_title_chars`, specific, spoiler-free for reaction-to-spoiler clips.
- `caption`: one line for the post; `hashtags`: ALWAYS include every `limits.required_hashtags` entry, plus
  #GTA6 and 2-4 relevant ones. `required_mentions` likewise.
- **Gore-safe start (YouTube ad rules):** if heavy violence/gore is described or likely in the first 7 seconds,
  move `start_word_index` later (or start on the reaction) so the first 7 s are clean. Move the start; do not drop
  the clip.
- No swear-heavy openings if the campaign `swear_filter` is off and platform rules matter: prefer a clean start.

## 4. layout
- `facecam`: default for streamers with a camera overlay (camera on top, gameplay below).
- `reaction`: reaction clips (camera large, gameplay small); forced automatically for `reaction-to-spoiler`.
- `track`: no camera / IRL / just talking. The pipeline falls back to `track` itself if no camera is detected.

## 5. Write highlights.json
Write `%USERPROFILE%\.autoclip\work\<job>\highlights.json`:
```json
{"clips": [{
  "start_word_index": 1204, "end_word_index": 1390,
  "title": "...", "hook": "...", "caption": "...", "hashtags": ["GTA6", "..."],
  "score": 87, "reason": "why this is the moment (one line)",
  "spoiler_level": "none", "layout": "facecam", "blur_word_ranges": [], "mentions": []
}]}
```
`score` is 0-100 (your confidence it performs). Sort best first. Validate: valid JSON, indexes inside the
candidate's `first_word..last_word`, every `spoiler_level`/`layout` one of the allowed values. Read `limits` in candidates.json: required
hashtags, mentions, `required_caption_phrases` (the caption MUST contain them), `max_title_chars`,
`banned_words`.

## 6. Render and report
Run `clip stream <same vod/args as before> --campaign <name>` again (the job is reused; transcribe is cached), or
`autoclip`-style: `.venv\Scripts\clip stream <vod> --campaign <name> --highlights <path>`.
Then read `exports\<job>\report.md` and tell Ahmad: which clips exported, which were blocked/rejected and why,
QA scores, and any cut-point warnings. Hard rules: only clip campaign-covered streamers; no isolated cutscenes;
every clip has hook + captions + reframe. Do not post anything. Posting is a later, separate (audited) step.
