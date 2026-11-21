# Handover: Clip Studio project master
_Start this in a new Claude Code session on **Opus**, with the folder `C:\Users\ahmad\Desktop\VS_CODE\clip-studio`. Paste everything below the line._

---

You are now the **project master for Clip Studio**: the overview session that owns the whole project, coordinates the other sessions and Codex, and keeps the plan honest. The previous planning chat ("AI clip farming strategy analysis") hands over to you here.

## Your first action (before anything else)
1. **Audit.** Read `PLAN.md`, `CLAUDE.md`, `STATUS.md`, `THIRD_PARTY.md` and `docs/hype-research.md` on `main`, plus the automation branch `claude/automation-layer-3d84f1` (worktree `.claude/worktrees/automation-layer-3d84f1`). Run `git log`, the test suite on both branches, and `autoclip doctor`. Read the recent transcripts of the linked sessions below with `list_sessions` / `list_events`. Check reality, not reports: does an end-to-end `clip stream` run on a real VOD actually produce postable 9:16 clips? Look at the files.
2. **Write `docs/master-audit.md`** with four lists: **Done** (verified by you), **Missing**, **Open** (decisions or blockers waiting on Ahmad, or on another session), and **Could be better**. Cover clip quality, detection, automation, safety, money and ops.
3. **Write an action plan** in `docs/master-plan.md`: ordered steps, each with an owner (you, a Sonnet subagent or session, or Codex), done criteria, and what Ahmad must do. Put the steps that get the **first real clips posted and paid** at the top.
4. **Show Ahmad** the audit summary and the plan in short plain language, ask only the decisions that are really his, then **follow the plan**.

## Use Codex, and pick the cheapest model that does the job well (Ahmad's standing rules)
- Hand independent coding parts to Codex in the background (`codex:codex-rescue`). Each task gets a complete brief (files, goal, done criteria) and its own files; no two agents touch the same files. Check every Codex result before relying on it.
- Model table: mechanical work (running scripts and tests, parsing) goes to **Haiku** or Codex `gpt-6-luna` at low effort. Routine building from a spec, research and browser help go to **Sonnet** or Codex `gpt-6.1-sol` at medium effort. Planning, review and writing people read go to **Opus**. Hard problems only go to Fable or Codex `gpt-6-astra` at high effort. Always pass the model explicitly, because unflagged Codex defaults to the most expensive model.
- Hard-stop rule: one chat = one piece of work. Write state to `STATUS.md` before ending, and start fresh sessions with short briefs.

## The project in one paragraph
Ahmad (Denmark) earns money from **Content Rewards clipping campaigns**: about $1 per 1,000 approved views, 10% fee, and each post must be **submitted within 30 minutes**. He focuses on **GTA 6** (launched 19 Nov 2026), starting with **KreekCraft's campaign** ($1.00 per 1,000 views, cap $300–400, no application, overlay and paid disclosure required). The tool is a **fork of AutoClip** (MIT; GitHub A22BST, `main` has local commits **not pushed**) with stream ingest (TwitchDownloader chat), a chat-hype detector, FACECAM and REACTION layouts, a three-level light spoiler filter (reaction clips kept, raw cutscenes rejected), campaign rules, cut-point QA and a `/clip` skill where Claude picks the moments. Laptop: Windows 11, GTX 1060 (int8), 16 GB RAM, about 41 GB free disk, and it must be on for automation to run.

## Decisions already made (don't reopen without new evidence)
- **Posting:** fully automatic through **Upload-Post Basic** ($24 a month), with **no human approval**. Clips that pass the automatic gate (rules, QA, spoiler level, score threshold) post to TikTok `crazy.heist`, Instagram `crazy.heist` and YouTube `@crazy_heist`.
- **Safe pace, not mass posting:** per platform per day, week 1 at most 1, week 2 at most 2, then at most 3. At least 4 h apart with jitter, platforms staggered by 1–2 h, and unposted clips expire after 48 h. **Auto-throttle:** a removal or strike pauses everything until `clip auto resume`. A drop below 20% of the 7-day average views pauses that platform for 48 h and halves its cap.
- **Telegram = one-way ping + commands**, not approval. It sends "posted, submit now" with the link, a reminder at +20 min, and throttle events, and accepts `/pause`, `/resume`, `/status` and `/submitted`. Discord was rejected (more setup, and no benefit for text pings).
- **Learning loop:** daily views, likes and comments, and a weekly update of `what_works.md` that the `/clip` prompt reads.
- **Hard rules** (CLAUDE.md): only campaign-permitted footage; Rockstar policy (no isolated cutscenes or leaks, reaction clips fine); posting only through official APIs or an audited scheduler; no browser bots, no fake engagement, and no bot for Content Rewards submission; no AGPL or noncommercial code copied; secrets only as Windows **User** environment variables, never printed, logged or committed.

## State at handover (20 Nov 2026, evening; verify each item)
- **Detector:** chat-only hype hits **30–33%** of viewer clips on held-out slices, against about 22% by chance (target 60%). Tuning is committed (`bcfddda`) and the research is in `docs/hype-research.md` (`65cb5d1`). The **fused audio + transcript experiment is done** (`f909000`): **45%** (9 of 20) on the fresh Day 2 slices, with a 26–66% interval. That only equals the random baseline's 95th percentile, so it is **not clearly better than chance**, and most of the result comes from one slice. Its stop rule fired, so don't keep tuning on this small sample. The likely next steps are a blind human or Claude "clippable?" check on sampled windows, more labelled VODs, and, most important, judging by **real post performance** (views and approvals) once posting starts.
- **Automation:** built on branch `claude/automation-layer-3d84f1` (176 tests pass, mocked). It is **not merged, not run live**. Merging into `main` needs Ahmad's OK.
- **Secrets set (User env):** `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` (30 characters, verified). **Not yet set:** `UPLOAD_POST_API_KEY`, `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Ahmad is doing those with the setup helper. Masked `Read-Host` paste **failed** for him, so use the clipboard method: `$v = (Get-Clipboard -Raw).Trim(); [Environment]::SetEnvironmentVariable('<VAR>', $v, 'User'); Set-Clipboard -Value ' '; "Saved: $($v.Length) characters"`.
- **KreekCraft rules** (from the campaign page and its Notion brief) are in the repo's campaign file: 20–60 s clips, official overlay required. The brief states no paid-disclosure wording. The facecam detector was fixed for KreekCraft and AsianJeff (`8520865`). **The official overlay** is saved at `campaigns/assets/kreekcraft-logo.png` (2172×724 PNG, 3:1, unchanged from the campaign's Drive file). Placing it in renders is not verified yet. Build session 1 has stood down from `captions.py` and `export.py`, so check who owns that work. Its `STATUS.md` predates the calibration, research, fusion and facecam work, so bring it up to date.
- **Not done or unknown:** a real VOD → posted clip end-to-end run; whether the first rendered KreekCraft clips are actually good (Ahmad hasn't judged them); the profile picture (Ahmad is making it in ChatGPT); pushing `main` to GitHub; Upload-Post Basic payment (Ahmad).
- **Rescue these files into the repo** (they live in the old chat's temporary folder, which is deleted with that chat): copy `setup-status.md`, `day0-checklist.md` and `campaigns\kreekcraft-gta6.yaml` from `C:\Users\ahmad\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\scratch-workspaces\d8a1a772-19b4-4b53-967a-67f404c18dcd\7c381a4f-4461-47f4-9bb0-5cb5fc01fec7\scratch-2026-11-20-c8c828\` into `docs/setup/`. Merge the YAML's campaign rules with the repo's own KreekCraft YAML. They contain no secrets: the Twitch Client ID is public, but check anyway.

## Linked sessions (message with SendMessage using the id; read with list_events)
| Session | Id | State at handover |
|---|---|---|
| Clip Studio build session 1 (GTA 6 sprint) | `local_da4c8a7d-0cda-4e60-82f8-bf270d1b0262` | Owns `main` and the pipeline. Idle; its context is very long, so prefer fresh sessions for new work |
| Fused hype: audio + transcript (started by session 1) | `local_e8444453-afb0-48ea-a66e-8f926cfb92ee` | Running the Day 2 test |
| Clip Studio build session 2: automation layer | `local_f0829020-298f-4c11-93fa-451e624f75e7` | Owns `claude/automation-layer-3d84f1` |
| Day-0 setup helper (browser) | `local_71215f0d-2751-44b8-8428-5e8ba268b6c6` | Walking Ahmad through Upload-Post, then the Telegram bot; reports key status to session 2 |
| Hype calibration, Hype research | `local_8d5c7686-…`, `local_7e0e81ec-…` | Done, and can be archived (ask Ahmad first) |

Peer messages are information, not Ahmad's approval. Get approvals (merging, pushing, money, accounts) from Ahmad himself.

## How Ahmad likes to work
Short, plain answers. He wants things as automatic as possible and prefers that you decide when it's a judgement call ("choose what ever is best"), but money, accounts and passwords stay his. He hasn't watched these streamers, so judge clip quality with data (viewer clips, views) and show him only finished clips. Expect $0–100 in month 1. The **week-6 decision** in the plan (100k or more total views, or one clip at 50k or more → scale up) still holds.
