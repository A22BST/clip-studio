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
- [~] Check 2 (see below): layouts/captions/hook/spoiler levels PASS; hype-vs-viewer-clips FAIL.
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
- Hype peaks vs viewer-made Twitch clips (Ahmad has not watched these streamers, so this replaced his own list). Windows come from
  candidates.json (viewer-clip signal OFF, top-15 per 3 h, +/-30 s). Required: >=60% of the 10 most-viewed clips inside a window.
  Day 1 slice (5:40-8:40): **50%**. Day 2 slice (the rendered one): **40%** (30% with interval overlap), but there the "top" clips have
  only 2-14 views (titles like "gta6", "test"), so that ground truth is weak. Chance level is ~20% (windows cover ~20% of the time), so the
  detector is ~2x chance but under the bar. Chat is sparse (~0.3-0.8 msg/s), which limits it. Not tuned on these 10 clips (overfitting).
  Next: calibrate weights on several more VODs with strong clip counts, or add audio-based peak detection.
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

## Build session 2 (2026-11-20): automation layer, branch `claude/automation-layer-3d84f1` (NOT merged into main)
Package `backend/autoclip/auto/` (CLI `clip-auto`, or `python -m autoclip.auto.cli`). 154 tests in `tests/auto/` pass.
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
