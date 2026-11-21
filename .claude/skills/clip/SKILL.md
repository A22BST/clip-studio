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
- candidates may carry viewer_clips (real Twitch clips of that moment, with view counts): a candidate with high-view viewer clips is strong proof of a real moment; read its title.

## 0b. HARD RULES: what counts as a clip (Ahmad's bar, 21 Nov 2026)
Ahmad's verdict on the first clips: the jet-ski dog clip was good "because it's unique"; a "free PS5" chat-bait
and a "chat spam stops" joke were "boring, no real value". So:
1. **A clip needs a moment type.** Put it in `reason` as `type: <one of>`:
   - `weird` (strange, unexpected or absurd thing in the game: a dog on a jet ski, a bed in a pool),
   - `unique-situation` (something that rarely/never happens, a glitch, a chase that goes wrong in a new way),
   - `rage-or-shock` (the streamer gets angry, crashes out, screams, laughs uncontrollably, is truly shocked).
   No type = no clip.
2. **NOT clips** (never pick these): talking to chat, giveaways/bait ("type 1 and I give away..."), reading
   comments or donations, jokes about chat spam, mission walkthroughs/explanations, loading or menu time,
   generic gameplay with nothing unusual.
3. **3-second stranger test:** would someone who has never seen the stream understand what is weird or funny
   within 3 s of the clip starting, without knowing KreekCraft or the mission? If not, skip it.
4. **Zero clips is a valid answer** for a slice of the VOD. Never pad to reach 5-10; fewer, better clips.
5. Candidates with `viewer_clips` (real Twitch clips with high view counts) are strong evidence of a real
   moment: read their titles, but still apply rules 1-3.

## 1. Decide per candidate (work through ALL of them)
1. Read the transcript and chat sample. Chat reacts 5-20 s AFTER the event, so the clip must START before the event
   with a little setup, and end on the payoff/reaction, not mid-sentence.
2. Choose `start_word_index` and `end_word_index` by copying the `[index]` numbers from the transcript (never
   compute indexes). Aim for `limits.min_duration_s`..`limits.max_duration_s` (about 20-60 s works best). Start on
   a sentence start where possible. The pipeline snaps to sentences/silence afterwards.
   **Virality rules (from `docs/virality-plan.md`):**
   - Target 20-35 s. Over 45 s only when the story needs it (the pipeline warns `long_clip`).
   - The payoff (the peak line, reaction or event) should land in the first 60-70% of the clip, not the last
     seconds. Trim dead lead-in; end 1-3 s after the payoff, not on housekeeping talk.
   - First second must show or say something concrete: start on a complete sentence, or just before the event.
     Avoid starting on swimming/menus/dark footage where the subject is not visible (`dark_opening` warning).
   - Complete event: setup, action, authentic reaction. A stranger must understand the first 2 s.
   - Prefer clips where the hook text matches what is spoken/seen in the first 2 s; the title promise must
     be paid off inside the clip, ideally by second 15.
3. Skip a candidate when: nothing actually happens, it is only chat spam, it needs context nobody has, or it is
   boring dead air. Quality over count: at most 10 clips, best first; zero is fine. Never invent moments the transcript does not support.
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
- `hook`: <= 6 words (hard max 8), shown for 2 s at the top, one line where possible (two lines cover the face), creates curiosity or states the payoff without spoilers
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

## 4b. Story evidence (required for every pick)
Every pick in highlights.json MUST include `story.setup`, `story.change` and `story.payoff`, each with
`start_s`, `end_s` (seconds in the ORIGINAL source video, read from `transcript.json` word timestamps,
never estimated from word indexes) and non-empty `text`:
- setup: the context a stranger needs. change: the action, surprise or reversal. payoff: the visible
  consequence, punchline or real reaction that delivers the hook's promise.
```json
"story": {
  "setup":  {"start_s": 120.0, "end_s": 123.0, "text": "He drives onto the pier"},
  "change": {"start_s": 128.0, "end_s": 130.0, "text": "A dog jumps on the jet ski"},
  "payoff": {"start_s": 132.0, "end_s": 134.0, "text": "He screams 'a DOG?!'", "speech_based": true}
}
```
Set `payoff.speech_based: true` when the payoff is spoken or vocal; its text must quote or describe it.
For a visual payoff, describe what the viewer sees. All three beats sit inside the word range, in order,
with at least 1 s (better 1-3 s of reaction) after the payoff. Boundary refinement re-checks the story
and may widen within campaign limits or reject.
Drop a pick whose payoff you can't explain plainly to someone who never watched the streamer, or
whose payoff evidence or timing is uncertain. Never pad to the campaign minimum with black screens,
loading, "Wasted" screens or unrelated footage. Usable duration = window minus black/dead spans and
transcript gaps longer than 6 s (Whisper dropouts, cutscenes); short pauses in gameplay are fine.
Zero picks is valid.

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
