Build the automation layer for Clip Studio, as described in section 5 and table rows 3a–3f of `PLAN.md`. Read `PLAN.md`, `CLAUDE.md` (hard rules and model routing) and `STATUS.md` first. Work on a new branch `automation-layer`, in a git worktree if possible, and never merge into `main`.

Context: I clip GTA 6 streams (KreekCraft's Content Rewards campaign) onto my accounts TikTok `crazy.heist`, Instagram `crazy.heist` and YouTube `@crazy_heist`. Build session 1 ("Clip Studio build session 1 (GTA 6 sprint)") built the clip pipeline on `main` and may still be working. I want it as automatic as possible: my only manual step is an Approve tap in Telegram. Posting goes only through official APIs or an audited scheduler: no browser bots, no fake engagement.

Do NOT edit build session 1's files: `backend/autoclip/stream/*`, the reframe, captions and rules code, the `/clip` skill, or the pipeline tests. Put new code in `backend/autoclip/auto/` with its own tests. Treat the job folder `clip stream` writes (MP4s plus per-clip metadata) as the interface. Read its real format from the code, and if something is missing, ask build session 1 with SendMessage.

Build, delegating 3a, 3c and 3d to Codex in the background (`codex:codex-rescue`, `--model gpt-6.1-sol`, medium effort), each with its own files and a full brief:
- 3a `watcher.py` + SQLite job queue + Windows Task Scheduler entry (every 30 min) + disk guard (pause below 10 GB free). It finds new VODs of active campaigns' streamers from `campaigns/*.yaml`.
- 3b The headless selection call: `claude -p "/clip <job>" --model sonnet` run unattended.
- 3c The Telegram bot (python-telegram-bot). It sends a preview video, title and caption with [Approve] [Reject] [Edit hook] buttons, supports `/pause`, `/resume` and `/status`, and only accepts my chat ID.
- 3d Posting through the Upload-Post API to TikTok, YouTube Shorts and Instagram Reels. Spread posts over the day. Right after posting, Telegram sends the post URLs with a "submit to campaign now" reminder, because Content Rewards requires submission within 30 minutes. Check whether Content Rewards has a submission API. Views tracking goes to a Google Sheet or a local CSV.
- 3e A weekly learn-and-report job.
- 3f A safety review by an Opus subagent. No path may post without passing the rules and the approval step. Level 2 auto-approve stays OFF and only becomes possible through config.

Secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `UPLOAD_POST_API_KEY`) are Windows User environment variables that I set myself. Read them from `os.environ`, falling back to `HKCU\Environment`. Never print, log or store them. Until they exist, use mocks. When you need them, give me a one-line PowerShell command using `Read-Host -AsSecureString`.

Done when, with mocks: a fake new VOD → job → clips → Telegram approval → posting call → tracker row. `/pause` blocks a queued post. pytest passes. Then a real end-to-end run once I have the accounts, where I approve the first real post. Commit on the branch, update `STATUS.md`, and report what is done, what is mocked, and what still needs me.
