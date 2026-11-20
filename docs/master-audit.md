# Master audit (20 Nov 2026, evening)

Checked by the project master session against the files, not the reports. "Verified" = I looked at it myself.

## Done (verified)
- **Pipeline works end to end on a real VOD (render side).** `~/.autoclip/exports/05a6dc5ea9164c73/`: 8 clips from the
  KreekCraft Day 2 slice, 1080x1920, 60 fps, h264 + aac, 25-44 s; 2 raw-cutscene picks rejected. Frames checked: FACECAM
  (camera top, gameplay below, captions on the seam), REACTION (big camera, gameplay blurred only during the reveal),
  hook text, `#ad Paid partnership`, logo slot. These are **placeholder-logo test clips: not postable**.
- **Campaign rules** in `campaigns/kreekcraft-gta6.yaml` (20-60 s, tags, caption phrase, overlay for the whole clip,
  disclosure 3 s, spoiler `light`). Setup-chat notes merged in (min payout $5, warmup, Tier 1 guide).
- **Setup files rescued** into `docs/setup/` (setup status, day-0 checklist, automation brief, setup YAML). Checked for
  secrets: only the public Twitch Client ID.
- **Detector tuning committed** (`bcfddda`), research in `docs/hype-research.md`, facecam edge fix `8520865`.
- **`autoclip doctor`: Ready.** CUDA OK; exports on CPU (libx264); "no LLM provider" is expected (selection is Claude via `/clip`).
- **Automation branch** `claude/automation-layer-3d84f1` (7 commits ahead of main): watcher, headless selection, gate,
  safe-pace scheduler, throttle, PAUSE file, Upload-Post client, Telegram ping, tracker, weekly learn. Mocked only.
- **Secrets (User env, length only checked):** `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` set (30 chars each).
- Tests: see "Test run" at the bottom.

## Missing (blocks the first real post)
1. **Official KreekCraft overlay** `campaigns/assets/kreekcraft-logo.png`. Without it every real clip is blocked by the rules
   (on purpose). The 636 kB file is in the campaign's Drive folder; the setup helper is waiting on Ahmad's yes to download it.
2. **Upload-Post Basic** not paid, `UPLOAD_POST_API_KEY` not set. Accounts not connected to Upload-Post yet.
3. **`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`** not set.
4. **`claude` CLI not logged in for headless use** (`claude -p` said "Not logged in" in session 2). Ahmad runs `claude` once.
5. **Automation not merged into `main`** and never run live (no real Upload-Post call, no real Telegram message).
6. **Automation config does not match the decisions yet.** Code defaults: Discord approval chat, level 1 (human tap), TikTok as
   hand-post. Decided: Telegram ping only, no approval, all three platforms via Upload-Post. Needed in
   `~/.autoclip/auto/config.yaml`: `chat: telegram`, `level: 2`, `auto_approve.enabled: true`, `manual_platforms: []`
   (once Basic confirms TikTok), and the campaign sidecar `campaigns/auto/kreekcraft-gta6.yaml` (end date, budget, submit link).
7. **`.[auto]` extra not installed** in `.venv`, **Task Scheduler tasks not installed** (dry run only).
8. **No clip judged by a human or by data.** Ahmad has not seen any clip, and no clip has ever been posted.

## Open (waiting on Ahmad or another session)
- Ahmad: yes/no to download the overlay (money/accounts rule: downloads need his yes).
- Ahmad: pay Upload-Post Basic, connect TikTok `crazy_heist`*, Instagram `crazy.heist`, YouTube `@crazy_heist`, save the API key.
- Ahmad: Telegram bot via BotFather, save token + chat id (clipboard method).
- Ahmad: log in the `claude` CLI once; OK to merge the automation branch into `main`; OK to push `main` to GitHub.
- Ahmad: Whop payout account (bank) - setup-status says details entered by him, not verified.
- Ahmad: reset the Twitch Client Secret (it was pasted into a chat earlier; STATUS.md flags it).
- Fused hype session (`local_e8444453`): Day 2 audio + transcript test still running; its files are untracked on `main`.
- Archive the finished sessions (hype calibration, hype research): Ahmad's OK.
- *Handle mismatch: `docs/setup/setup-status.md` says TikTok is `crazy_heist`, the handover says `crazy.heist`. Ahmad confirms.

## Could be better
**Clip quality**
- Hook and `#ad` text are small (about 4% of frame width) and sit on the face. TikTok hooks are usually large, high-contrast,
  upper-middle. Make the hook 2-3x larger and keep it clear of the face box.
- The facecam crop includes KreekCraft's sub counter and red bar; REACTION's gameplay strip shows his webcam a second time.
- Cut-point QA is noisy on game audio: 6 of 8 clips carry "could not confirm" warnings, one exported with a real cut-off
  first word (QA 75). Under auto-post only QA >= 90 posts (`min_qa` 90), which would drop that one: good, but check the
  QA scale is right before going live.
- Files are 17-64 MB at 60 fps; fine for upload, but 30 fps would halve size and render time.
**Detection**
- Chat-only hype: 30-33% held-out vs about 22% by chance (target 60%). Not good enough to trust alone. Claude's `/clip`
  pick from the transcript is doing the real work. Fused audio + transcript result pending.
- Viewer clips (Twitch API) are the strongest signal we have and are not used as an input, only as ground truth. Using the
  top viewer clips of a VOD as candidates is cheap and needs no new research.
**Automation**
- Mocked only. Upload-Post response shapes, delayed TikTok URLs and Telegram are untested live.
- Telegram commands work only with `chat: telegram`, which is the decided mode anyway.
- Minor items from the Opus review are still open (copy approved file to an immutable path, old-preview approve, token URL in INFO logs).
**Safety**
- Fully automatic posting has never been watched once. The first posts should run in a supervised "dry" mode (render + gate
  + Telegram "would post" message) for one day before real posting.
- Rockstar policy and campaign rules are in the gate; KreekCraft requires the warmup process and Tier 1 audience
  (>=40% US/UK/CA/AU). A Danish new account may fail that audience rule: watch approval rates.
**Money**
- $5 minimum payout per clip = 5,000 approved views per clip, or it pays nothing. Expect most early clips to earn $0.
- Upload-Post $24/month is the only cost; break-even is about 27,000 approved views a month.
**Ops**
- Disk: **24 GB free** (not 41). A 3 h slice is about 4.2 GB, the guard pauses below 10 GB: keep one slice at a time and delete sources.
- The laptop must be on; nothing runs while it sleeps.
- `main` is 8 commits ahead of GitHub, not pushed: one disk failure loses the work.

## Test run (20 Nov, this session)
See `docs/master-plan.md` step 0 for the result; filled in below when the run finished.
