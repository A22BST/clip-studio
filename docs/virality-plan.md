# Virality plan (21 Nov 2026)

Goal: more clips that reach 5,000+ qualifying views. Evidence is in `docs/virality-research.md` (sourced,
every number has a URL or is marked *unsourced*) and `docs/virality-frame-review.md` (our Day 2 clips, frame by frame).
Honest summary: **there is no public gaming-specific benchmark for most of this**. Most numbers below are test
defaults, not proven optima. The plan therefore ranks cheap fixes first and puts the rest into A/B tests.

## 1. Findings (short)

**From the research**
- Hook within ~1 s is creator advice (YouTube/Hoyos interview, Jan 2025), TikTok ad guidance says state the idea within 3 s.
  No verified second-by-second retention curve exists for gaming clips. In a 9.2M-view TikTok study 24% of viewers skipped before 20% of the video (CHI, 2020-22 data).
- Length: Buffer (1.1M TikToks): >60 s got 43% more median reach than 30-60 s. Reels (Socialinsider): median views 4.7k at 1-30 s, 8.6k at 30-45 s, 10.4k at 45-60 s. Observational, not gaming. Kreek's own Hub Shorts range 14-60 s; his best ever is 52 s. So: do not force 15 s.
- Payoff: no rule found. Defaults to test: context by 3 s, first action/reaction 3-5 s, main payoff 8-15 s (clip 15-25 s) or 15-30 s (clip 30-45 s), 0.5-2 s of reaction after.
- Layout: no controlled comparison. Test 30/70 (gameplay first) vs 60/40 (reaction first); keep head with 10-15% headroom; the campaign requires KreekCraft's overlay.
- Posting (Buffer, local time): TikTok Sun 09:00 / Mon 13:00; Reels Wed 18:00, Thu 09:00; Shorts Fri 16-19:00, Sat 19:00. For US/UK/CA/AU the plan tests UTC 18:00-21:00 (UK evening + NA afternoon) and 23:00-02:00 (NA evening); AU evening is 08:00-10:00 UTC. Cadence for a new account: TikTok 5/wk, Reels 3-5/wk, Shorts 5/wk.
- Winners in this niche are specific action+reaction titles and humor (Sonder: meme edits averaged 420.8k vs 90.5k for news recaps). KreekCraft Hub titles: "Throws poop at NPC", "Too family friendly for GTA 6".
- Watermarks, low resolution and reposts reduce reach (Instagram, historical secondary source). We export 1080x1920 clean; keep it.
- **Discrepancy to settle:** the live campaign page shows **$0.50/1,000** (min payout $2.50 TikTok/Instagram, $5 YouTube); the older beta page and our brief say $1/1,000, $5 min. Ahmad/master should check the real terms before judging earnings.

**From our Day 2 clips (8 files, frames viewed)**
1. Hook sits at y 80-190, inside the top UI zone, on 8/8 (and is absent at t=0, fades in/out).
2. Payoff late on at least 5/8 (e.g. gunfight title phrase at 33-38 s of 38 s; pool reaction 25-28 s of 29 s).
3. Streamer sub counter / overlay clutter kept on 8/8; duplicate camera in the "door" clip.
4. Dark or unrecognizable first frame (snake: 89% pixels below luma 32; robbery 55%; dog clip opens on swimming, no dog).
5. Camera panel takes 38% (65% in "door") for the face; two-line hooks cover the face.
6. In-game subtitles at the bottom collide with the app UI and our captions.

## 2. Ranked changes

Owners: Codex = `codex:codex-rescue`, model + effort as stated. "Sonnet" = Sonnet session. Hook geometry, `#ad` and sub counter crop are already owned by `codex/hook-size` (A2) and master-plan C3; they are listed so nothing gets forgotten, not duplicated.

| # | Change | Expected impact | Effort | Owner | Done when |
|---|---|---|---|---|---|
| 1 | **/clip selection rules**: 20-35 s target, payoff in first 60-70%, start on a concrete moment, hook <= 6 words, end 1-3 s after payoff | High (fixes late payoff + weak opens on most clips) | S | Done here (SKILL.md) | Rules in `.claude/skills/clip/SKILL.md`; Day 3 clips reviewed against them |
| 2 | **Warnings in the report**: `dark_opening`, `long_clip`, `hook_too_long` (and `late_payoff` if cheap) | Medium (catches what #1 misses; no more blind QA 100) | S | Done here (Codex gpt-6.1-sol medium) | Tests green; warnings appear in `report.md` |
| 3 | **Hook safe zone and visible at t=0**: top inset >= 250 px (under the app UI), hook on frame 0 (no fade-in), hold 2.5-3 s, one line | High on 8/8 clips | S | Codex gpt-6.1-sol medium, **after** `codex/hook-size` merges (same file `captions.py`) | Frame check on 3 clips: hook visible at 0.0 s, clear of top 250 px and face |
| 4 | **Cleaner facecam crop** (no sub counter, no double camera) + tighter camera panel (30/70 default) | High (more gameplay, cleaner look) | M | Codex gpt-6.1-sol medium (master-plan C3) | Frame check on 3 clips; face with headroom, overlay attribution still there |
| 5 | **Cold open / outcome-first option**: allow `/clip` to put the peak 0.5-1 s first or start right before the event; auto-trim lead-in so payoff <= 15 s | High but needs data | M | Sonnet (skill) + Codex gpt-6.1-sol medium (trim helper) | 5 clips of the next VOD where payoff lands <= 15 s without cutting context |
| 6 | **Opening frame picker**: if first frame is dark, move start forward <= 2 s or choose a thumbnail-like frame | Medium | M | Codex gpt-6.1-sol medium | `dark_opening` warnings drop to 0 on a 8-clip batch |
| 7 | **Subtitle cleanup**: hide/crop in-game subtitles or keep one subtitle system; word captions above the bottom UI (y < 1536) | Medium | M | Codex gpt-6.1-sol medium | No overlap of captions with UI mask on 3 clips |
| 8 | **Posting-time slots** (uses `backend/autoclip/auto/`, off limits here): TikTok Sun 14:00 / Mon 18:00 UTC; Reels Wed 23:00 / Thu 14:00 UTC; Shorts Fri 21:00-00:00 UTC; plus UK-evening (19:00 UTC) and AU-evening (09:00 UTC) tests; DST-aware | Medium | S | Sonnet (config, master decides, auto/ owner) | Schedule lists the slots; first week's posts spread across them |
| 9 | **A/B tests through the learning loop**: tag every post with hook style (cold open / text / spoken / question), length bucket (<25, 25-45, >45 s), layout (30/70 vs 60/40), slot; compare 24 h / 72 h / 7 d views, avg watch time, country mix | High long-term | M | Sonnet (auto/ owner) | `what_works.md` shows the tags per post and a per-tag average after week 1 |
| 10 | **Eligible earnings metric**: rank by clips that pass 5,000 views and the 40% country gate, net payout, not total views | Medium | S | Sonnet | Weekly report includes it |

Order of work: 1, 2 (done) -> 3 and 4 as soon as `codex/hook-size` merges -> 5, 6, 7 in the Day 4 batch -> 8-10 with the automation owner.

## 2b. Added 21 Nov (Ahmad's bar, sound, tools)

**Ahmad's bar for a clip** (now hard rules in `.claude/skills/clip/SKILL.md`, section 0b): a clip needs something weird or unexpected, a unique situation, or the streamer raging/shocked. Chat bait, giveaways, reading comments, mission walkthroughs are not clips. Moment type is required, 3-second stranger test, zero clips per slice is fine.
**Twitch viewer clips as candidates (C2): done here.** `prepare()` fetches the VOD's viewer clips (best effort), feeds them to hype scoring and writes `viewer_clips` (views, title, offset) into each candidate.

| # | Item | Verdict | Effort | Owner | Done when |
|---|---|---|---|---|---|
| 11 | **Story/payoff check before render** (setup, change, payoff; re-check after boundary refinement) | Best of the gta6clipper ideas; extends rules 1-3 | M | Codex gpt-6.1-sol medium | Report lists setup/payoff per clip; rejects clips with no payoff |
| 12 | **Frame sheet review** (open/payoff frames, flag menus, wrong footage, hook that misdescribes) | Cheap, partly done (`dark_opening`) | M | Codex gpt-6.1-sol medium | Contact sheet in the export folder per job |
| 13 | **Rage/voice-jump candidates** from audio (sudden loudness rise, scream, laugh) as an independent signal | Matches "crashes out" bar; `audio_hype.py` already has the base | M | Codex gpt-6.1-sol medium | Candidates tagged `voice_jump`; check on Day 3 VOD |
| 14 | **Finished-media QC** (frozen/black, silence, loudness), hold failures | Medium | M | Codex gpt-6.1-sol medium | Failing clip held, not posted |
| 15 | **Learn from our posts at 24/48 h** (view stats per post ID, per hook/length/layout tag) | Same as #9, uses real numbers | M | Sonnet (auto/ owner) | Weekly `what_works.md` |
| 16 | **Optional SFX layer** at the payoff (OFF by default, one restrained accent) | Unproven (no causal evidence found); small test only | M | Codex gpt-6-luna low after the license list is chosen | A/B of 10 clips with/without |

Details and sources: `docs/virality-gta6clipper-ideas.md` (reimplement ideas only; project has no license, copy no code, run nothing from it; live mode, game-banner OCR and music bed ranked low) and `docs/virality-sound-and-tools.md`.

**Sound verdict.**
- No direct evidence that SFX or meme stingers raise views on streamer clips. Treat as a test, not a fix.
- **Background music: keep OFF.** TikTok promotional content needs Commercial Music Library tracks, Instagram's music library is for non-commercial use, YouTube Content ID can claim or block, and TikTok can mute a clip whose sound is removed. The campaign pays per verified view, so any mute or block costs money. Stream audio itself may already contain third-party music; prefer clips where it does not.
- **License-safe SFX if we ever add them:** Pixabay (commercial use, no credit), Mixkit SFX Free License (no credit), Freesound CC0 assets only (check each one), YouTube Audio Library (no Content ID claims). Keep a local allowlist with source, license and checksum; do not bulk-scrape. Discord/Google Drive packs: a shared folder is not a license (meme music, movie samples and repacked stock are the usual traps). Ahmad decides; nothing downloaded.
- ffmpeg design for the SFX layer (delay at payoff, duck the effect under speech, loudnorm -14 LUFS) is in the sound doc.

**quso.ai and repurpose.io: keep our pipeline + Upload-Post.** quso: $39/mo (300 processing minutes), $49/mo (600), transcript-based clipping that is weak for silent gameplay, no public API. repurpose.io: $35/mo Starter (3 accounts per network, 5,000 posts/mo), cross-posting only, no chat-aware highlight finding. Neither beats our chat-hype + Claude selection + facecam layout + rules check. Possible later use of repurpose.io: only for source watching/backup.

## 3. A/B test design (cheap)

- Never post near-duplicates of one moment (repost penalty + campaign rules); test across different moments instead.
- Compare only same-platform, same-day-of-week clips; with 3-5 posts/week sample sizes are small, so only act on differences > 2x after >= 8 posts per bucket.
- First tests: (a) length <25 s vs 25-45 s, (b) text hook vs spoken-first open, (c) layout 30/70 vs 60/40.
