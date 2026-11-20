# Clip Studio — project rules

Fork of AutoClip (MIT, artbyjazi/autoclip) turned into a GTA 6 streamer-clip pipeline.
Spec: `PLAN.md` (sections 3, 4, 7 matter most). Progress: `STATUS.md`. Borrowed code: `THIRD_PARTY.md`.

## Hard rules (plan section 7)
- Only clip streamers or creators whose campaign covers it or who gave written permission.
- Follow Rockstar's policy: no isolated cutscenes or leaked footage. Reactions to story moments are fine,
  with spoiler-free titles and the reveal blurred if needed. A campaign's own spoiler rule overrides ours.
  Spoiler filter stays LIGHT, three levels only: `none`, `reaction-to-spoiler` (keep, REACTION layout,
  spoiler-free title/hook), `raw-cinematic` (reject).
- Post only through official APIs or an audited scheduler. No browser bots, bought views, engagement pods,
  or automated likes/comments.
- Every clip gets a hook, captions and a reframe. No raw re-uploads.
- Respect licenses: keep MIT notices, credit borrowed code in THIRD_PARTY.md, copy NO AGPL or noncommercial
  code (hotclip, clips-studio, gta6-stream-clipper = ideas only; supoclip = avoid; OpenShorts `cloud/` = never).
- Model routing follows Ahmad's global table (below). Update `STATUS.md` at the end of every session.
- Ask Ahmad before creating any account, API key or token.
- Never put secrets in the repo.

## Model routing (Ahmad's global table, since 2026-11-14)
| Work | Claude | Codex |
|---|---|---|
| Mechanical: run scripts/tests, parse, convert, copy in a fixed format | Haiku | gpt-6-luna, low |
| Routine: build from a spec, research, scoring, triage, browser form filling, scheduled watchers | Sonnet | gpt-6.1-sol, medium |
| Text people read, planning, review of delegated work, ambiguous tasks | Opus | (Claude only) |
| Hard problems, whole-process analysis, only when Ahmad asks | Fable | gpt-6-astra, high |

Always pass the model explicitly (`--model`/`--effort` for Codex): the Codex default is the most expensive one.
One chat = one piece of work; hard-stop and continue in a fresh chat after compaction or ~2 h.

## Environment
- Windows 11, GTX 1060 (Pascal: use int8, no fast fp16; NVENC unavailable with the current driver -> libx264),
  16 GB RAM, ~41 GB free disk. Python 3.11 venv at `.venv` (MediaPipe needs <3.13).
- Tools: Gyan ffmpeg full build, yt-dlp, uv (winget); TwitchDownloaderCLI in `C:\Users\ahmad\tools\TwitchDownloaderCLI`.
- Activate: `.venv\Scripts\activate`; run `autoclip doctor`, `pytest`.
- Two agents never touch the same files.
