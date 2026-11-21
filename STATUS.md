# STATUS

## Build session 1 (2026-11-20): DONE, with the hype-accuracy check failing (see Check 2)
Test source: KreekCraft "GTA 6 LIVE (FULL GAME) ALL ENDINGS | DAY 2" (Twitch VOD 2933758895, picked by
Ahmad's setup helper). Campaign: KreekCraft GTA 6 Clipping (`campaigns/kreekcraft-gta6.yaml`).

- [x] Fork `artbyjazi/autoclip` -> `A22BST/clip-studio` (upstream remote kept); PLAN/CLAUDE/STATUS/THIRD_PARTY docs
- [x] Step 0: ffmpeg (Gyan full 9.0.2), yt-dlp, uv, Python 3.11, `.venv`, `.[gpu,dev]`. `autoclip doctor` OK, CUDA visible,
      int8_float32. TwitchDownloaderCLI 1.56.5 is NOT in winget: unzipped from the GitHub release to
      `C:\Users\ahmad\tools\TwitchDownloaderCLI`. NVENC unusable with driver 582.78 -> libx264 (fine).
- [x] Step 1 baseline (3 clips, AutoClip unchanged, centre-crop TRACK reframe). No LLM API key exists, so the clips were
      picked by Claude from the transcript instead of AutoClip's built-in provider. Finding: unchanged AutoClip drops the
      streamer entirely (gameplay centre-crop only), which is why FACECAM/REACTION exist.
      Output: `C:\Users\ahmad\.autoclip\exports\514403339be441a3\` (for Ahmad to judge).
- [x] 2a ingest: `stream/ingest.py` (TwitchDownloaderCLI wrapper, chat JSON -> `ChatLog`, trim-aware, disk guard). A 3 h slice
      (2:00:00-5:00:00) + chat stored together (4.2 GB).
- [x] 2b `pipeline/hype.py` (Codex gpt-6.1-sol/medium). Peaks + `stream/hype_eval.py` (viewer-clip ground truth, needs Twitch
      client id/secret from Ahmad; NOT run yet).
- [x] 2c `pipeline/layouts.py`, `facecam.py` + export integration (Codex). Facecam detector re-worked by me after it found
      nothing on real footage (small corner webcam, no border).
- [x] 2d `pipeline/rules.py`, `profanity.py`, `stream/campaigns.py`, hook overlay (Codex); disclosure overlay, logo overlay,
      caption phrases, deadline fields added by me.
- [x] 2e `/clip` skill (`.claude/skills/clip/SKILL.md`), `clip stream`, `stream/pipeline.py`, cut-point QA (`pipeline/cutqa.py`)
- [x] 2f Opus review: 6 blocking issues found and fixed (see git log).
- [x] Final run (2026-11-20): `clip stream <KreekCraft Day 2 VOD, 2:00:00-5:00:00 slice> --campaign kreekcraft-gta6-test`.
      10 picks -> **8 exported 9:16 clips (25-44 s), 2 raw-cinematic windows rejected**. Files + `report.md`:
      `C:\Users\ahmad\.autoclip\exports\05a6dc5ea9164c73\`. Timings on the GTX 1060 / i5-8300H: download 3 h + chat ~6 min,
      transcribe 3 h ~30 min (large-v3-turbo, int8_float32, chunked), render 8 clips ~12 min (reframe/encode on CPU).
- [x] Check 1: `autoclip doctor` passes, Whisper transcribes on CUDA.
- [~] Check 2 (see below): layouts/captions/hook/spoiler levels PASS; hype-vs-viewer-clips FAIL (calibrated, still under the bar: see "Hype calibration").
- [x] Check 3: `pytest` = 480 passed, 24 skipped (AutoClip's own slow/golden/e2e media tests). New tests: hype, rules, campaigns,
      layouts/facecam, profanity, hook/disclosure, cut-point QA, ingest/chat, stream pipeline, hype eval, transcribe chunking.

## Check 2 detail (plan section 8)
PASS (checked by eye on contact sheets of all 8 clips):
- FACECAM: camera top (found by the corner face detector, rect ~272x208 px on 720p), gameplay below, captions on the seam, hook (2 s),
  `#ad Paid partnership` (3 s) and logo overlay for the whole clip.
- REACTION: camera ~65%, gameplay strip; the gameplay blurs only inside the blur window (the reveal words) and is sharp before/after.
  Reaction-to-spoiler clip kept with a spoiler-free title ("He did NOT expect who opened that door").
- Two raw-cinematic windows (cutscene dialogue) were rejected. A swear ("f***") is masked in captions and muted in audio.
- A reaction-to-spoiler clip with no camera found is BLOCKED (it would show the reveal unblurred), never exported.
FAIL / not met:
- Hype peaks vs viewer-made Twitch clips: STILL FAILS the 60% bar after calibration; see "Hype calibration" below.
- Cut-point QA (re-transcribing 5 s edges) is noisy on game audio: several clips show "could not confirm" warnings, one false error was
  caused by a bleeped word (fixed). It lowers the QA score but never blocks a clip. Ahmad should still listen to the clip edges.

## Known gaps / for Ahmad
- `campaigns/assets/kreekcraft-logo.png` (official logo from the campaign materials) is missing: real KreekCraft clips are BLOCKED by
  rules until it exists. `kreekcraft-gta6-test.yaml` uses a generated placeholder: pipeline test only, never post those clips.
- Twitch Client ID/secret (env `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET`) needed for the viewer-clip hype check.
- Whisper: transcription of long audio is now chunked (20 min) to avoid MemoryError on 16 GB.
- Twitch Client Secret was pasted into chat by Ahmad for the hype check: it was used only as a process-local variable and never written to
  disk, but it is in the chat transcript, so reset it in the Twitch developer console. Keep it in the user env var `TWITCH_CLIENT_SECRET`.
- Nothing was pushed to GitHub (commits are local on `main` of the A22BST/clip-studio fork).
- Next (build session 2, not started): automation layer, plan section 5.

## Hype calibration (2026-11-20, chat-only, viewer-clip signal OFF)
Ground truth: viewer clips of KreekCraft Day 1 (VOD 2932147800). Six aligned 3 h chat slices cached
(`scripts/hype_fetch_chat.py`), split BEFORE scoring: CALIBRATION hours 0-3, 6-9, 12-15; HELD-OUT 3-6, 9-12, 15-18.
Spec kept: top_n=15 per 3 h, tolerance 30 s. Every slice yields 15 distinct windows (they cover ~21-27% of the time, so chance is ~22%).
Tools: `scripts/hype_calibrate.py` (per-slice hit rate), `scripts/hype_tune.py` (grid on a smooth view-weighted hit share, because
10 clips/slice is too few to tune on directly).

Top-10 most-viewed viewer clips per slice, hit rate strict / overlap (before -> after; "floor 50" = only clips with >=50 views, n in brackets):

| Slice | Set | Before (strict/overlap) | After (strict/overlap) | After, floor 50 (n) |
|---|---|---|---|---|
| 0-3 | calib | 70% / 70% | 70% / 70% | 75% / 75% (4) |
| 6-9 | calib | 40% / 40% | 50% / 60% | 50% / 60% (10) |
| 12-15 | calib | 50% / 70% | 60% / 80% | 50% / 100% (2) |
| **3-6** | held-out | 40% / 50% | 40% / 50% | 40% / 50% (10) |
| **9-12** | held-out | 20% / 20% | 30% / 30% | 25% / 25% (4) |
| **15-18** | held-out | 20% / 20% | 20% / 20% | 0% / 0% (1) |
| Held-out mean | | 27% / 30% | **30% / 33%** | 22% / 25% |
| Day 2 2:00-5:00 (weak clips) | sanity | 40% / 30% (earlier check) | 30% / 30% (60% with >=10 views, n=5) | |

Result: **the 60% bar is NOT met on held-out slices (best 30% strict / 33% overlap, chance ~22%).** The detector is ~1.4x chance there.
Smooth objective (view-weighted share of clips hit, clips >=10 views): calib 0.65 -> 0.72, held-out 0.28 -> 0.30.
What changed in `hype.py` (only things that helped on BOTH halves): `bin_s` 5 -> 10 s and `w_emote` 0.8 -> 2.0; 5 new generic reaction
tokens in the phrase table (yooo, !clip, NotLikeThis, kreekCrashout, swearing); new `HypeConfig` knobs (min_users, max_user_share, user_cap,
emote_cap) with unchanged behaviour. Tried and rejected: 15 min baseline, longer/shorter windows and merge gaps, a short-baseline burst
signal, other participation gates (all fitted calibration slices, 0.72-0.76, but dropped held-out slices to 0.15-0.25).
Why chat-only cannot reach 60% here: (1) chat is 0.4-0.8 msg/s, so a 10 s bin holds ~7 messages; (2) several of the most-viewed clips
sit at moments with almost no chat reaction (e.g. a 1,290-view clip with 12 messages near it, ranked 67th; a 1,712-view clip with 28 messages);
(3) held-out slices 9-12 and 15-18 have only 4 and 1 clips with >=50 views, so their "top 10" are mostly 5-30 view clips (noise);
(4) many real moments rank 11-20 (just outside top 15) and top_n is fixed by spec. The only slices with reliable ground truth
(3-6 and 6-9) give 40-50% strict. The remaining untested lever is audio loudness (needs the video; ~3 h download per slice), and a
second opinion from the transcript (LLM scoring of candidate windows), which this check did not cover.
Caveat: the final default was chosen with a pooled look across all six slices after the held-out numbers were seen (the first
calibration-only fit, bin 10 s + 15 min baseline + w_emote 2.0, scored 0.76 on calibration but 0.16 on held-out, so it was dropped),
so the held-out numbers above are slightly optimistic. Clip lists are cached at `~/.autoclip/hype_cal/` (no credentials in them).

## Build session 2 (2026-11-20): automation layer, merged into main on 2026-11-20 (Ahmad approved)
Package `backend/autoclip/auto/` (CLI `clip-auto`, or `python -m autoclip.auto.cli`). 171 tests in `tests/auto/` pass (full suite: 651 passed, 24 skipped).
Session 1's files were not edited; it is used only through `clip stream`, `report.json` and `highlights.json`.

Built (what exists, tested with mocks):
- 3a `watcher.py` (Twitch Helix: new VODs of campaigns that have a sidecar `campaigns/auto/<stem>.yaml`; 3 h slices; skips live
  streamers, old VODs, duplicates; first run only baselines), `diskguard.py` (pause below 10 GB), `winsched.py` (4 Task Scheduler
  tasks as XML: tick every 30 min, bot at logon, daily track, weekly report; **dry run unless `clip-auto install-tasks --apply`**, not installed).
- 3b `select.py`: `claude -p "/clip <job>" --model sonnet`, headless note (no render, no shell), validated, one retry with the error.
- 3c approval: `approval.py` + **Discord bot (default)** `discord_bot.py`/`discord_notify.py` (embed + Approve/Reject/Edit hook modal,
  /pause /resume /status, owner + channel only, 9 MB preview ladder) and **Telegram bot as an alternative backend** (`config.chat`).
- 3d `uploadpost.py` + `poster.py` (local queue, spread over config slots, `gate` before every upload, never resends after a request id),
  `submit.py` (30-minute "submit now" reminders at +10/+20 min with a Submitted button), `tracker.py` (CSV `~/.autoclip/auto/tracker.csv`),
  `publisher.py` (interface), `manual_platforms` (default `[tiktok]`: free Upload-Post plan has no TikTok, so TikTok is sent to the chat as file + text to post by hand).
- 3e `learn.py`: weekly Sonnet job writes `~/.autoclip/auto/what_works.md` (read by the headless selection) and sends a report.
- Safety: `gate.py` is the only authority to post (fails closed): not paused, approved by the owner, file hash unchanged since approval,
  render report `exported`, not raw-cinematic, campaign live and under budget, rules re-checked, platforms allowed, daily cap, approval TTL.
  Level 2 auto-approve is OFF and needs `level: 2` AND `auto_approve.enabled: true` in `~/.autoclip/auto/config.yaml`.

Mocked: Twitch API, the clip pipeline subprocesses, `claude -p`, Upload-Post, Discord/Telegram HTTP. NOT verified live: Upload-Post
response shapes (analytics nesting, delayed TikTok URLs), Discord gateway (never connected), real `claude -p` selection.
- Content Rewards has NO public submission/views API (checked): submission stays a manual tap; the bot sends links + deadline.

Needs Ahmad before a real end-to-end run:
1. `claude` CLI is **not logged in** for headless use (`claude -p` says "Not logged in"): run `claude` once in a terminal and log in.
2. Secrets as User env vars: `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `DISCORD_OWNER_ID`, `UPLOAD_POST_API_KEY` (Twitch ones exist).
3. Upload-Post: a paid plan for TikTok (until then TikTok is a hand-post), profile name (config default `crazyheist`).
4. `campaigns/assets/kreekcraft-logo.png`; campaign end date, budget and submit link in `campaigns/auto/kreekcraft-gta6.yaml`.
5. `uv pip install -e ".[auto]"` (discord.py, python-telegram-bot[job-queue]); then `clip-auto install-tasks --apply` once approved.
6. Merge decision: branch is not merged; `pyproject.toml` gained the `auto` extra and `clip-auto` script.

### Safe-posting additions and the Opus safety review (3f)
Ahmad (via the strategy session) asked for no-approval, safe-volume posting. Decision asked and confirmed in chat: **human approval stays the
default** (level 1). No-approval is a config switch (`level: 2` + `auto_approve.enabled: true` in `~/.autoclip/auto/config.yaml`), not the default.
Added (all configurable under `post:` / `throttle:`): per-platform daily caps ramping 1 / 2 / 3 by account week, >= 4 h between posts on one platform
(+ up to 30 min jitter), one post row per platform staggered 60-120 min, best QA first, clips expire after 48 h unposted (`schedule.py`);
auto-throttle: last 3 posts < 20% of the 7-day average -> platform paused 48 h and cap halved, logged (`throttle.py`, run after `clip-auto track`);
`clip-auto report-removal <platform>` pauses everything until `clip-auto resume`; a `PAUSE` file next to `auto.db` is checked by the gate before
every post (`clip-auto pause` / `resume` create / remove it); `posted_to_submit.csv` (every URL + its 30-minute deadline) in `~/.autoclip/auto/`;
level-2 auto-approval code path (`approval.auto_approve_pending`, off unless both switches are set; the gate re-checks everything).
NOT built (spec changed several times, needs a decision): `TelegramManualPublisher` (file as document + per-platform captions + "Posted on X" buttons),
YouTube Data API / Instagram Graph comment pulling, and the comment-themes part of the learning loop (`learn.py` uses views only).
The clip-auto CLI is `clip-auto pause`, not `clip auto pause` (the `clip` CLI is session 1's).

Opus review result (before these additions): no path posted without rules + approval, with one exception, now fixed:
- BLOCKING (fixed): the headless `claude -p` selection (reads untrusted chat/transcripts) ran with write access to the repo and config; it now runs with
  its cwd set to the job's own work folder, the skill text is passed in the prompt, and Bash/Edit/web tools are disallowed (`select.py`, `claude_cli.py`);
  the weekly learn run gets no tools and a scratch cwd.
- MAJOR (fixed): a failed/denied post re-queued the same clip (duplicate upload risk): now the clip is retired (`post_failed`/`expired`), and the idempotency key is per clip + platform.
- MAJOR (fixed): `TickLock` used `os.kill(pid, 0)`, which TERMINATES a process on Windows: replaced with a safe liveness check.
- MAJOR (fixed): a Telegram group chat id is refused (any member could approve).
- Open MINOR items (ALL CLOSED in build session 3, see below): the upload re-reads the file after the hash check (copy to an immutable `approved/<sha>.mp4` would close it); an old preview's Approve
  button approves the newest version after a hook edit; a dismissed Discord edit modal leaves the clip in `editing`; httpx INFO logging could show the Telegram
  token URL if logging is ever raised to INFO; the hand-post message includes the local file path.
- Bug found by the new end-to-end test and fixed: with one post row per platform the gate rejected the 2nd and 3rd platform after the 1st marked the clip `posted`.

### Telegram ping (added later)
One-way Telegram ping is ON whenever `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, in addition to the approval chat (Discord by default):
`CompositeNotifier` sends every text message (without buttons) to Telegram, never videos or previews. After each post: "Posted on <platform> -
submit to Content Rewards now (30 min)", campaign, deadline, URL on its own line; reminders at +10 and +20 min until submitted; throttle, pause and
removal notices. Telegram commands (`/pause /resume /status /submitted <url>`, only from `TELEGRAM_CHAT_ID`) work when the Telegram bot runs, i.e. with
`chat: telegram`; in Discord mode the Telegram side is send-only and `/submitted` is done with the Submitted button or by the Discord bot.

## Hype fusion experiment (2026-11-21, one capped round): 60% NOT reached
Protocol `docs/hype-fusion-protocol.md` (pre-registered, committed before scoring; stop rule added on Ahmad's instruction).
Day 2 VOD 2933758895, verdict slices 0-3 h and 3-6 h (chosen by clip totals after freezing), sanity slice 2:00-5:00.
Pooled top-10 viewer-clip hit rate (20 clips, strict = overlap): fused-Claude **45%** (CI 26-66), fused-RRF 40%, chat-only 35%,
transcript-only 30-35%, audio-only 5%; random 23% mean, 45% p95. 0-3 h: fused 7/10, 3-6 h: 2/10. Stop rule triggered (<50%):
no tuning, no second round. Fused did not clear the random 95th percentile. Even a perfect ranker over the pooled candidates
would reach 65% (pool-all 13/20). Clippable fraction (blind judges, rubric in protocol): fused-Claude 20% (Claude judge) / 50%
(Codex judge) vs chat 10/30%, audio 14/34%, transcript 7/30%: fused is highest on both, judges differ a lot in strictness.
New code (opt-in, not wired into `clip stream`): `pipeline/audio_hype.py` (DSP, 4 s/hour of audio), `pipeline/transcript_hype.py`,
`stream/fusion.py`, `scripts/hype_fusion_run.py`; tests included. Rankings, candidates and judge files: `~/.autoclip/fusion/`.

## Build session 3 (2026-11-21): fully automatic mode is the shipped default (branch `claude/auto-level2-5368f5`)
Ahmad's decisions: posting is fully automatic through Upload-Post Basic ($24/month), NO human approval; Telegram is a one-way ping plus
`/pause /resume /status /submitted`; Discord is dropped from the default path (code kept, `chat: discord` still works).
- Config: `docs/auto-config.example.yaml` is the template (`chat: telegram`, `level: 2`, `auto_approve.enabled: true`, `min_qa: 90`,
  `manual_platforms: []`, safe-pace values). `clip-auto init-config [--force]` copies it to `~/.autoclip/auto/config.yaml` (written for this
  laptop; `clip-auto status` shows "Mode: level 2 fully automatic ..."). Code defaults stay fail-closed (level 1, no auto-approve) when the
  file is missing; `AutoConfig.chat` default is now `telegram`, `manual_platforms` default `[]`.
- Upload-Post pricing (checked 2026-11-21 on upload-post.com/pricing and docs): TikTok is NOT on the Free plan but IS included from Basic
  ($24/month, unlimited uploads, 5 profiles). So `manual_platforms: []`. Unverified live: TikTok direct-post privacy (`PUBLIC_TO_EVERYONE`) for a
  brand-new account; check on the first live post.
- Campaign `campaigns/auto/kreekcraft-gta6.yaml`: `budget_usd: 6045`, new `cap_per_clip_usd: 300` (budget estimate counts at most $300 per post),
  `ends_at: null` (the page shows no end date), `submit_url` = the campaign page. Rate $1/1k is in `campaigns/kreekcraft-gta6.yaml`.
- Level 2: auto-approve runs in `post_cycle`; below `min_qa` a clip is rejected and never sent; above it the chat gets a FYI preview with only a
  Reject button ("AUTO-APPROVED ... posts after the 60 min review window"). Every post still goes through the whole `gate.py` (tested: raw-cinematic,
  pause, QA, caps). "Posted on <platform>, submit now" now shows the deadline in Copenhagen time and UTC plus the URL; a reminder goes out at +20 min
  (`submit.reminder_minutes: [20]`, then "Deadline passed") until `/submitted`. `/submitted` without a URL logs the only waiting post, else lists them.
- `clip-auto tick --dry-run` (also `post-due --dry-run`): watcher, jobs, selection, previews, auto-approve and scheduling run for real; the upload does
  not. Each queued post gets one "WOULD POST" (or "WOULD NOT POST" + gate reasons) ping, evaluated at its scheduled time; nothing is claimed or counted.
  A normal tick afterwards posts the same queue (so a dry run on a real VOD leaves approved clips queued).
- MINOR items closed: (1) approval copies the clip to read-only `~/.autoclip/auto/approved/<sha>.mp4` (hash taken from the copy) and the clip path
  switches to it in the same transaction, so what is uploaded is what was approved; (2) Approve buttons carry a 12-char preview token (`a:<id>:<token>`):
  an old preview cannot approve a newer version; (3) clips stuck in `editing` return to review after 10 min (`restore_stale_edits`, runs every cycle);
  (4) httpx/httpcore forced to WARNING on package import and in the CLI/bot entry points (Telegram token URL never logged); (5) hand-post message no
  longer has the file path and every chat message passes `redact_paths`.
- Not done / for later: approved copies are never deleted (disk use grows ~10-30 MB per clip; add cleanup after posting); `clip-auto.exe` launcher is
  missing from the main `.venv` because another process holds `clip.exe` (re-run `uv pip install -e ".[auto]"` when it exits; Task Scheduler uses
  `python -m autoclip.auto.cli`, so nothing depends on it); secrets (`UPLOAD_POST_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) still unset;
  nothing was run against the real services.

## Project master session (2026-11-20/21, Opus): current state
Owner of the overall plan: `docs/master-audit.md` (audit) and `docs/master-plan.md` (ordered steps A/B/C with owners).
Handover from the planning chat: `docs/setup/handover-master.md`; its setup files are rescued in `docs/setup/`.
- Done: audit + plan; automation merged into `main` and pushed; bigger hook/#ad text (Codex, `4b1d104`); logo moved below the hook (`4afbb46`);
  fully automatic mode merged (`5701044`, Ahmad confirmed "fully automatic" on 21 Nov); official KreekCraft overlay at
  `campaigns/assets/kreekcraft-logo.png` (2172x724 RGBA, git-ignored because the repo is public); fused hype tested and NOT adopted (45%, stop rule).
- Decisions by Ahmad: fully automatic posting (no tap); first clip posted by hand by Ahmad; TikTok handle `crazy_heist`; USB stick D: (NTFS,
  label CLIPDATA, 58 GB) is the data drive from now on (move `AUTOCLIP_HOME` there).
- Running / next: Day 2 re-render with the real overlay (job `05a6dc5ea9164c73`) -> frame check -> send Ahmad "a dog on a jet ski" for a hand post;
  Day 3 (VOD 2934981732, 1:40-4:00) downloaded, transcription hit MemoryError while the render ran: re-run `clip stream ... --prepare-only` alone;
  then move `~/.autoclip` to `D:\autoclip` and set User env `AUTOCLIP_HOME`.
- Waiting on Ahmad: Upload-Post Basic + `UPLOAD_POST_API_KEY`; Telegram bot + `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`; `claude` CLI login;
  Twitch Client Secret reset; archive the old automation session (`local_f0829020`) from the sidebar.
- Sessions: build session 1 and fused-hype told to stop (done). Setup helper `local_71215f0d` walks Ahmad through Upload-Post/Telegram.
  New sessions are started by the master so they report to it.

## Free-model chain (2026-11-21, branch `claude/free-model-chain-0660c4`): BUILT, mocked tests only
Plan decided by Ahmad in the CoWorkOS chat (free LLMs by default; Claude and Codex stay free for real work). Built by Codex
(gpt-6.1-sol, medium), reviewed by the build session. Provider facts and caveats: `docs/free-model-presets-verified-2026-11-21.md`.
- Chain: `providers/chain.py` (`ChainProvider`, `complete_text`, `complete_validated`). Entries are provider BUCKETS (one account each) with
  an ordered `models` list; model failures fall to the next model in the bucket, rate limit / daily quota / auth / connection fall to the next
  bucket. Daily usage is counted per provider (failed calls too) in `<auto_dir>/chain-usage.json` with per-provider reset (Google: midnight
  Pacific, others UTC); a spent bucket is skipped until reset. Per-bucket `max_prompt_tokens` guard (Groq free is 8K tokens/min, so it only
  gets small prompts). Claude is OFF (`chain.allow_claude = false`), an explicit opt-in last entry. Local Ollama is the last free entry and is
  skipped unless the tick lock is absent and no job is running (unknown = skipped).
- Default order: zai-glm-flash, nvidia-nim, openrouter-free, google-ai-studio, cloudflare-workers-ai, groq, aihubmix, pollinations, ollama.
  Change it in settings (`chain.entries`); `autoclip config chain` lists buckets, key present/missing, usage today.
- `auto/learn.py`: weekly report on the chain (`learn.backend = chain`, the default; `claude` switches back).
- `auto/select.py`: `selection.backend = claude | chain`. The chain path inlines `candidates.json`, `what_works.md`, the campaign yaml and the
  /clip skill body, gets plain text back (no tools, no files), writes `highlights.json` itself, keeps `validate_highlights` and retry-with-error.
  DEFAULT STAYS `claude` until Ahmad has seen the comparison numbers.
- Provider and model per clip: `selection_meta.json` in the job folder, copied into the clip's DB row and tracker CSV columns
  (`provider`, `model`); existing DBs migrate. The claude path records `claude-cli` + model. Old clips stay blank.
- Comparison: `scripts/selection_compare.py JOB VOD [--offset-s N] [--claude] [--only a,b] [--clips-json f] [--dry-run]` scores each keyed
  bucket/model and Claude against the top viewer clips of the VOD (recall of top-N, precision of picks). Needs a prepared job
  (`clip stream ... --prepare-only`) and Twitch app creds (or a cached clips json). One job is a small sample: run several.
- Verified: mocked tests only (pytest: chain fallback on 429/quota/connection/bad JSON, model fallback, daily budget + reset, persisted
  counter, token guard, Cloudflare account id, ollama gating, Claude off by default, learn/select via chain, tracker migration). NO live
  provider call was made (no keys exist). Preset URLs, model IDs and limits were read from each provider's own pages on 2026-11-21, not tested.
- Preset caveats: Z.ai free IDs lowercased by inference and sit under legacy pricing; NVIDIA trial limits not published on pages read;
  Groq free is 8K tokens/min (small prompts only); AIHubMix needs a one-time $1 top-up (10 calls total before); Google free-tier data is used
  to improve products per the pricing page (EEA exception NOT found there: confirm at aistudio.google.com/docs/terms); Pollinations now
  REQUIRES a key (the "no key" note was out of date); OpenRouter 50/day until $10 credit is bought.
- Keys Ahmad adds (`autoclip config set-secret NAME`): `zai-glm-flash`, `nvidia-nim`, `openrouter-free`, `google-ai-studio`,
  `cloudflare-workers-ai` plus `cloudflare-account-id`, `groq`, `aihubmix`, `pollinations`. Start with Z.ai, OpenRouter, Google, NVIDIA.
- Keys set 2026-11-21 (live one-call test OK): `openrouter-free`, `google-ai-studio`, `zai-glm-flash`, `nvidia-nim`. Not set: groq, cloudflare, aihubmix, pollinations. Live findings: NVIDIA `deepseek-ai/deepseek-v4-flash` (EOL 2026-08-07) and `moonshotai/kimi-k3` (EOL 2026-10-15) return 410, only `minimaxai/minimax-m3.1-flash` works: fix the preset. Some free models 429/503 transiently (OpenRouter gemma/ernie/ling, Google 3.8-flash, Z.ai 4.7-flash). `set-secret NAME --clipboard` added (reads clipboard, then clears it).
- Next: add 2-3 keys, run `selection_compare.py` on a prepared job with `--claude`, then decide the selection default and order.
- Known: `tests/auto/test_safe_posting.py::test_best_qa_goes_first_and_the_rest_wait_or_expire` fails on main too (clock-dependent, not touched).
- 21 Nov (free-model chain build session): free-model chain built on branch `claude/free-model-chain-0660c4`, mocked tests only, selection default
  still `claude` pending the comparison; see section "Free-model chain". Not pushed or merged.
