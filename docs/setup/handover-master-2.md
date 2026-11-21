# Handover: Clip Studio master, chat 2
_Start a new Claude Code session on **Opus** in `C:\Users\ahmad\Desktop\VS_CODE\clip-studio`, and paste everything below the line. Keep this chat short: review, decide, delegate._

---

You are the **project master for Clip Studio** (chat 2). Chat 1 did the audit, the plan, the first post and the moves below. Read first, in this order: `STATUS.md` (the "Project master" sections and the "Free-model plan"), `docs/master-plan.md`, `docs/master-audit.md`, `docs/campaign-scout.md`, and `to-post/CAPTIONS.txt`. Then check reality (git log, `D:\autoclip`) before acting.

## Ahmad's standing rules (also in your memory files)
- **Decide routine steps yourself** (merges after review, pushes to his fork, branches, tests, delegating). Ask him only about money, accounts, keys, joining campaigns, downloads from the web, and real product choices.
- **Token budget is tight** (42% of the weekly Claude limit was used on day 1). Codex (`codex:codex-rescue`, always with `--model gpt-6.1-sol --effort medium`, or `gpt-6-luna` low for mechanical work) does coding, web research and runs. Claude helper sessions run on Sonnet at medium effort. Codex's sandbox can't write `.git`: create the worktree and branch yourself, and commit for it.
- **Start helper sessions yourself** (`start_session`), so their reports come to you and not to Ahmad. Never message old sessions to change a decision: they can't take it from you, and they end up asking Ahmad.
- **Clips must be unique:** something weird happens, or the streamer crashes out. No chat-talk, giveaway or walkthrough clips. Fewer, better clips; zero for a VOD is fine.
- **No burned-in "#ad Paid partnership".** `#ad` goes in the caption. 5 hashtags per post: `#ad #GTA6 #KreekCraft #GrandTheftAutoVI` + 1 specific tag.
- **No bot submits to Content Rewards.** Ahmad submits each link within 30 minutes of posting. Posting is fully automatic through Upload-Post once it's set up (Ahmad confirmed), with the safe pace and a dry-run first day.
- **Data lives on the USB D:** (`AUTOCLIP_HOME=D:\autoclip`). Keep it plugged in.

## State (21 Nov)
- First post: TikTok `crazy_heist`, the jet-ski clip, 21 Nov. On 22 Nov the same clip goes on Instagram `crazy.heist` and YouTube `@crazy_heist` (warmup day 3).
- **KreekCraft now pays only $0.50 per 1,000 views.** Next campaigns to join: AsianJeff (Twitch, $1) and Dylan Page (YouTube, $1). Ahmad joins; then add their campaign YAMLs and watcher sidecars.
- Running: session "Clip quality & virality" `local_b022b69f-b6c5-478e-ab04-a8e15c0173d8` (branch `claude/virality-plan-a38caa`): `docs/virality-plan.md`, unique-moment rules in the /clip skill, viewer clips as candidates, an SFX plan, ideas from gta6-clipper (NO license, so ideas only, no code), and a quso/repurpose verdict. Review its diff and frames, then merge.
- Decided elsewhere (CoWorkOS chat, see STATUS "Free-model plan"): run selection on free LLMs by default, with Claude opt-in. It's not started yet; make it a Codex task.
- Waiting on Ahmad: Upload-Post Basic + `UPLOAD_POST_API_KEY`, Telegram bot (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`) with the setup helper `local_71215f0d`, `claude` CLI login, Twitch secret reset, a check that Whop pays out to Denmark, joining AsianJeff and Dylan Page, a yes/no on downloading the Discord SFX/music packs, and archiving old session `local_f0829020` plus (after the helper) the planning chat.
- After keys exist: run `clip-auto init-config`, then a `clip-auto tick --dry-run` day, then go live (`master-plan` B4-B6).

## Your first actions
1. Review and merge the virality branch when it reports.
2. Set up the next campaigns as soon as Ahmad has joined.
3. Keep clips coming: each day, render the newest VOD of every joined streamer. Show Ahmad only clips that pass the unique-moment bar and a frame check, in `to-post/` with captions, until the automation is live.
