# Master plan (from 20 Nov 2026)

Goal order: **first real clips posted and paid**, then automatic, then better clips.
Owners: **Ahmad**, **Master** (this Opus session: planning, review, merges), **Sonnet** (session or subagent), **Codex**
(`gpt-6.1-sol` medium for building, `gpt-6-luna` low for mechanical). No two agents on the same files.

## A. First real clips posted (target: 21-22 Nov)
| # | Step | Owner | Done when | Ahmad does |
|---|---|---|---|---|
| A1 | DONE 20 Nov (2172x724 RGBA PNG, kept out of git). Download the official "KreekCraft Overlay" (636 kB, campaign Drive) to `campaigns/assets/kreekcraft-logo.png` | Day-0 helper (has the browser) | File exists, rules check passes on a real clip | Says **yes** |
| A2 | Running (Codex, branch `codex/hook-size`). Bigger hook + `#ad` text, kept off the face box (FACECAM and REACTION) | Codex gpt-6.1-sol medium, reviewed by Master | Frame check: hook >= 2x current size, readable on a phone, tests pass | - |
| A3 | Running: Day 3 VOD 2934981732, 1:40-4:00, prepare started 21 Nov. Render postable clips from the newest KreekCraft VOD with the real overlay (`clip stream ... --campaign kreekcraft-gta6`) | Sonnet session | 5-8 clips pass rules + QA >= 90, frames checked by Master | - |
| A4 | Ahmad sees the best 3 finished clips (only finished clips) | Master | Ahmad has watched them | Watches 3 clips (5 min) |
| A5 | Upload-Post Basic paid, 3 accounts connected, `UPLOAD_POST_API_KEY` saved (clipboard method) | Ahmad + Day-0 helper | Key set (length check only) | Pays, connects, saves key |
| A6 | Telegram bot (BotFather), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` saved | Ahmad + Day-0 helper | Both set | Creates bot, saves values |
| A7 | First post: 1 clip per platform (week 1 cap), then **submit to Content Rewards within 30 min**. Ahmad chose: **first clip by hand**, automation after B | Ahmad by hand (Master sends the clip + caption) | 3 public posts, 3 submissions | Submits each link in Content Rewards |

## B. Fully automatic (target: 22-23 Nov)
| # | Step | Owner | Done when | Ahmad does |
|---|---|---|---|---|
| B1 | DONE 20 Nov (`cdd8656`, 757 tests pass). Merge `claude/automation-layer-3d84f1` into `main`, full test suite green | Master | Merged, tests pass | Says **OK to merge** |
| B2 | Config for the decided mode: `chat: telegram`, `level: 2`, `auto_approve.enabled: true`, `min_qa: 90`, `manual_platforms: []` (if Basic includes TikTok); campaign sidecar with budget, end date, submit link; `uv pip install -e ".[auto]"` | Sonnet | `clip-auto status` shows the right mode | - |
| B3 | Log in the `claude` CLI once for headless `/clip` | Ahmad | `claude -p "say ok"` works | Runs `claude`, logs in |
| B4 | Live smoke test: one Telegram ping, read-only Upload-Post account check, one dry tick on a real VOD that ends in "would post" pings, no real post | Sonnet session, reviewed by Master | All three work against the real services | - |
| B5 | One supervised day: real posting on, Master checks every post and the gate log | Master | 3 posts at the right pace, pings arrive, nothing posts that should not | Submits links when pinged |
| B6 | Install the Task Scheduler tasks (`clip-auto install-tasks --apply`) | Sonnet | Tasks run every 30 min while the laptop is on | Says **OK** |

## C. Better clips and safety (from week 1)
| # | Step | Owner | Done when |
|---|---|---|---|
| C1 | Fused hype (audio + transcript) Day 2 result; adopt only if >= 45-50% on the frozen protocol | Session `local_e8444453` | Result in `STATUS.md`, kept or dropped |
| C2 | Use the VOD's top Twitch viewer clips as extra candidate windows for `/clip` | Codex gpt-6.1-sol medium | Candidates include viewer-clip windows, tests pass |
| C3 | Facecam crop excludes the streamer's sub counter; REACTION strip avoids the double webcam | Codex gpt-6.1-sol medium | Frame check on 3 clips |
| C4 | Open minor safety items (immutable approved copy, token URL in logs) | Codex gpt-6.1-sol medium | Tests + Master review |
| C5 | Daily views, weekly `what_works.md`, throttle check against real numbers | Automation; Master reviews week 1 | First weekly report arrives in Telegram |
| C6 | DONE 20 Nov. Push `main` to GitHub (backup) | Master | `origin/main` = `main` | Says **OK to push** |
| C7 | Reset the Twitch Client Secret (it was pasted in a chat) and save the new one (clipboard method) | Ahmad | New secret set | Does it |

## Decision points
- **Week 6** (about 1 Jan 2027): 100k+ total views or one clip at 50k+ -> scale up (more streamers and campaigns).
  Otherwise change streamer or hook style and judge again in 4 weeks.
- After 2 weeks: if approval rate at Content Rewards is low (audience rule: >=40% US/UK/CA/AU), check account targeting.

## Hard stops
One chat = one piece of work. A and B each run in fresh Sonnet sessions with short briefs; Master keeps `STATUS.md` current.
