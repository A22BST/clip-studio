# Clip farming with Claude Code + Codex: GTA 6 first, as automatic as possible

## Context
Ahmad has seen videos about using Claude and Codex to "clip farm": cut long videos and streams into short clips, post them on TikTok, YouTube Shorts and Instagram Reels, and get paid. He wants:
- the best strategy, building on open-source tools others have published (fork and merge, not from scratch)
- streamer clipping, where the **chat tells us when a moment is clippable**
- **GTA 6 first**, because it launched on 19 Nov 2026 and is the biggest trend right now
- an end state that is **as automatic as possible**
- the work handed to Claude Code, which delegates to Codex

Constraints: English clips, side project at first (scale up if it pays), this laptop (GTX 1060, i5-8300H, 16 GB RAM, about 41 GB free; Python 3.13, Git, Node, Codex and gh are installed; no ffmpeg, yt-dlp or Docker). Ahmad is fine with downloading extra tools that add value.

## 1. What earns money (research, Nov 2026)
| Way to earn | Pay | Verdict |
|---|---|---|
| **Paid clipping campaigns** (Content Rewards, formerly "Whop clipping", plus others) | Median listed rate about **$1.09 per 1,000 views** (gaming and streamer campaigns about $1.00–1.40). **GTA now:** a GTA RP streamer campaign at about $1.50, and a GTA 6 music campaign at $0.70 capped at $35 per clip. About a 10% fee comes off, and you are paid only for approved clips and verified views | **Start here.** The footage and permission come with the campaign, it works from Denmark, and there is no follower minimum |
| Own channel with platform ad revenue | Shorts in Europe pays about $0.03–0.10 per 1,000 views. TikTok Creator Rewards appears unavailable in Denmark | Weak. Rockstar's policy treats footage as **non-commercial** and allows takedowns at any time |
| Clipping as a service (a monthly fee from a streamer) | Hundreds to thousands of dollars a month per client | **Phase 3.** Campaign stats become the portfolio |

Facts the plan depends on:
- Expect **$0–100 in month 1**. A trend raises the ceiling but also the competition, and speed plus hook quality decide who wins.
- **Rockstar's video policy:** isolated cutscenes, the ending and big story reveals get taken down, and so does footage from leaks. Cutscenes inside a commentated playthrough are allowed. **Chat spikes often happen at story reveals**, so the pipeline keeps the *reaction* (the valuable part) and leaves out raw cinematic footage. Reaction clips are kept, and the filter is deliberately light (section 3).
- **YouTube (Sept 2026):** heavy gore in the first 7 seconds removes ad monetization. The hook can't open on that.
- Templated mass-produced clips get penalized. Every clip needs a real hook, captions and a reframe.
- **Posting is automated only through official routes.** TikTok and YouTube make API posts from unaudited apps private, so we use an audited scheduler (Upload-Post, Postiz Cloud or Blotato). Browser bots, bought views and engagement pods get accounts banned and campaign payouts rejected.

## 2. Open-source projects to build on (checked on GitHub, 20 Nov 2026)
| Repo | Stars / license | What we take |
|---|---|---|
| [artbyjazi/autoclip](https://github.com/artbyjazi/autoclip) | 463 / MIT | **The base (fork).** Runs natively on Windows, Python 3.11, CLI plus review UI, `doctor`, resumable stages, picks clips by word index, no reframe pans across cuts, caption styles, −14 LUFS audio |
| [mutonby/openshorts](https://github.com/mutonby/openshorts) | 9.4k / MIT (except its `cloud/` folder) | Ideas and ported code: the SCREENCAST and panel layouts (good for facecam over gameplay), the SPLIT two-speaker layout, hook overlays, and the Upload-Post integration. It needs Docker, so it is only an optional side-by-side test |
| [RealAdii/clipper-skill](https://github.com/RealAdii/clipper-skill) | 12 / MIT | Claude in the Claude Code session picks the moments (no API key), plus its cut-point check that re-transcribes each clip's first and last 5 seconds |
| [lay295/TwitchDownloader](https://github.com/lay295/TwitchDownloader) | 4.1k / MIT | A CLI that downloads Twitch VODs and the full **chat replay as JSON** |
| [xenova/chat-downloader](https://github.com/xenova/chat-downloader) | 1.2k / MIT | YouTube Live and Twitch chat (last updated Nov 2025, so check it still works) |
| hotclip, clips-studio ("Clips Kitty", which mentions GTA 6), vanz-0/gta6-stream-clipper | AGPL / no license | **Ideas only, no code copied:** chat-heat detection, facecam detection, a swear filter |
| supoclip | Noncommercial | Avoid. Its license blocks client work |

Keep each project's MIT notices and list borrowed code in `THIRD_PARTY.md`.

## 3. The GTA 6 streamer pipeline
```
source: a campaign streamer's Twitch, Kick or YouTube VOD (later: the live stream)
 → ingest      TwitchDownloader CLI (VOD + chat JSON) / yt-dlp; chat for Kick and YouTube in the same format
 → transcribe  AutoClip faster-whisper large-v3-turbo, int8 on GTX 1060, CPU fallback
 → hype        hype.py: a score for every 5 s window = chat messages per second vs the rolling 5-minute average (z-score)
               + weights for hype emotes and phrases (KEKW, LUL, OMEGALUL, ????, "CLIP IT", "no way", W/L spam)
               + unique chatters + audio loudness spikes (ffmpeg ebur128) + clips viewers already made (Twitch API, with
               their position in the VOD). Chat peaks 5–20 s after the event, so each window starts 30 s before the
               peak and ends 10 s after. Keep the top 10–20 peaks and merge any less than 60 s apart
 → select      /clip skill: Claude reads the transcript + a chat sample for each candidate window, picks start and end
               by word index, writes the hook line, title, caption and hashtags (GTA/campaign tags),
               and gives each clip one of three **spoiler levels** (light-touch, so reaction clips survive):
                 • none: a normal clip, nothing changes
                 • reaction-to-spoiler: the streamer's reaction is the focus → KEEP it, use the REACTION layout
                   (camera large, gameplay small, and gameplay blurred during the reveal seconds only), and keep the title
                   and hook spoiler-free ("his reaction to THAT mission 😭", not the plot point)
                 • raw-cinematic: mostly cutscene or ending footage with little reaction → reject
               It also keeps heavy gore out of the first 7 s (by moving the hook start, not dropping the clip)
 → QA          clipper-skill cut-point check (no starts or ends mid-word)
 → layout      new FACECAM layout: camera on top (found by face detection + a static-region check), gameplay below,
               captions on the seam. Falls back to TRACK when there is no camera.
               New REACTION layout: camera takes about 65% of the frame, gameplay a small strip, with an optional blur window
 → captions    AutoClip bold_pop + a 2 s hook overlay + a swear filter (bleep or mask) when the campaign requires it
 → rules       campaigns/<name>.yaml: length, required tags, "today's stream only", banned content → a QA score
 → approve/post/track: see section 5
```
Podcasts or business talk become a second track later. They use the same pipeline without the hype stage and with the SPLIT layout.

## 4. Sprint plan (speed matters while GTA 6 is new)
**Day 0, Ahmad (about 2 h):**
- Sign up as a clipper on Content Rewards and join 2–3 **GTA 6 or GTA streamer campaigns**. Note each one's rules: length, tags, "today's stream only", spoiler rules.
- Create one TikTok, one YouTube channel and one Instagram account for GTA 6 clips. Use them normally for 2–3 days while the pipeline is being built.
- Register a free Twitch developer app (for the client ID).

**Build session 1 (new Claude Code session on Sonnet in `C:\Users\ahmad\Desktop\VS_CODE\clip-studio`; Codex `gpt-6.1-sol` at medium for the parallel rows; no two agents on the same files):**
| Step | Who | Done when |
|---|---|---|
| 0. Fork and clone AutoClip (GitHub account A22BST, keep the upstream remote). winget installs of the full Gyan ffmpeg build, yt-dlp, uv, Python 3.11 and TwitchDownloaderCLI; `.[gpu]` | Sonnet (Haiku for mechanical parts) | `autoclip doctor` passes with CUDA visible |
| 1. Baseline: run AutoClip unchanged on 30 minutes of a GTA campaign VOD | Sonnet | Clips play in the review UI, and Ahmad judges them |
| 2a. Stream ingest (VOD + chat JSON, times lined up) | Sonnet | A 3 h GTA VOD and its chat are stored together |
| 2b. `hype.py` | Codex | On a VOD Ahmad has watched, at least 7 of the top 10 peaks are real moments |
| 2c. FACECAM + REACTION layouts (+ a blur window) | Codex | GTA footage renders with the camera on top and gameplay below, with no cut-off face. The REACTION layout blurs only the seconds it is given |
| 2d. `rules.py` + campaign YAML + hook overlay + swear filter | Codex | A deliberately too-long clip or one missing its tags is blocked |
| 2e. `/clip` skill (chat windows + three-level spoiler tagging + gore-safe hook start) + `clip stream <vod> --campaign X` | Sonnet | One command turns one VOD into 5–10 reviewed clips. Reaction clips around story moments are kept, with spoiler-free titles, and raw cutscenes are dropped |
| 2f. Review of the Codex changes | Opus subagent | No blocking issues remain |
**Goal: the first GTA clips posted (by hand) by day 3.**

**Build session 2 (week 2): automation**, section 5.
**Later:** Kick and YouTube chat support, the optional OpenShorts side-by-side test (Docker Desktop + WSL2, about 15 GB, with WSL2 turned on by Ahmad), the podcast track, and live mode.

## 5. End state: as automatic as possible
```
[Windows Task Scheduler every 30 min while the laptop is on]
 1 watch    watcher.py: new VODs from each active campaign's streamers (Twitch API / yt-dlp) → job queue
 2 fetch    VOD + chat, with the source deleted after rendering (disk guard: pause if less than 10 GB free)
 3 detect   transcribe + hype
 4 select   headless `claude -p "/clip <job>" --model sonnet` (uses the plan, no API key)
 5 render   layout + captions + QA + rules → a QA score per clip
 6 approve  Telegram bot (Ahmad creates the token): preview video + title + [Approve] [Reject] [Edit hook]
 7 post     the scheduler API (Upload-Post / Postiz Cloud) → TikTok, Shorts and Reels, spread over the day
 8 submit   to the campaign through its API if one exists (Codex checks), otherwise a one-tap list of links in Telegram
 9 track    Google Sheet: campaign, rate, platform, URL, views, submitted, approved, paid. A daily job pulls views
10 learn    a weekly job: Claude updates a "what works" file the /clip prompt reads + an earnings report to Telegram
```
- **Level 1 (from the start):** only the Approve tap is manual, about 5 minutes a day.
- **Level 2 (after week 6, if approval rates are high):** clips above a QA score Ahmad sets post with no tap. Each is still reported, and Ahmad can delete it within the hour.
- **Kill switch:** `/pause` in Telegram. Campaigns that run out of budget or pass their end date are turned off automatically.
- **Live mode (later):** read chat through Twitch IRC (read-only anonymous access) and keep a rolling 10-minute streamlink buffer. On a spike, clip that segment → pipeline → Telegram within 5 minutes. This suits "today's stream only" campaigns.
- **Limits:** the laptop must be on. An always-on box or a cloud GPU is a later upgrade.
- **Accounts Ahmad creates himself:** the scheduler account (connected to his TikTok, YouTube and Instagram), the Telegram bot token, the Twitch developer app, and a Google Cloud project for the YouTube Analytics API.

| Step | Who | Done when |
|---|---|---|
| 3a. watcher + queue + Task Scheduler + disk guard | Codex | A new VOD becomes a finished job with no one touching it |
| 3b. headless `claude -p` selection | Sonnet | It runs unattended and writes valid highlights.json |
| 3c. Telegram approval bot + `/pause` | Codex | Approve, Reject and pause work from the phone |
| 3d. scheduler posting + view pulling + tracker | Codex | One approved clip posts publicly to all three platforms, and its views appear the next day |
| 3e. weekly learn and report | Sonnet | The report arrives in Telegram |
| 3f. safety review of the automation | Opus subagent | No path posts without passing the rules and the approval step at its level |

## 6. Decision points
- **Week 6:** if total views reach 100k or more, or one clip passes 50k, scale up (more streamers and campaigns, Level 2, possibly a second account set). If not, change streamers or hook style and judge again in 4 weeks.
- **Month 3+:** sell monthly clipping to 3–5 GTA streamers, using the same pipeline. Every component is MIT, so client work is allowed.

## 7. Hard rules (go in the project's CLAUDE.md)
- Only clip streamers or creators whose campaign covers it or who gave written permission.
- Follow Rockstar's policy: no isolated cutscenes or leaked footage. Reactions to story moments are fine, with spoiler-free titles and the reveal blurred if needed. Follow each campaign's rules (a campaign's own spoiler rule overrides ours).
- Posting only through official APIs or an audited scheduler. No browser bots, bought views, engagement pods, or automated likes and comments.
- Every clip gets a hook, captions and a reframe. No raw re-uploads.
- Respect licenses: keep MIT notices, credit borrowed code, and copy no AGPL or noncommercial code.
- Model routing follows Ahmad's global table, and `STATUS.md` is updated at the end of every session.

## 8. Verification
1. `autoclip doctor` passes, and a 1-minute test transcribes on CUDA.
2. On a GTA VOD Ahmad has watched, compare the top 10 hype peaks with his own list. Check that clips start before the event, the FACECAM layout is correct, captions are in sync, the hook overlay shows, and the spoiler levels work: include one raw cutscene (it must be rejected) and one big reaction to a story moment (it must be kept, with the REACTION layout and a spoiler-free title).
3. `pytest` passes, with AutoClip's tests plus new tests for hype, rules and cut-point QA.
4. Automation: a test channel's new VOD → Telegram preview → Approve → a public post on all three platforms → a tracker row → views the next day. `/pause` stops a queued post.

## Sources
[Content Rewards clipping data](https://contentrewards.com/articles/clipping-data) · [GTA 6 clipping on Content Rewards](https://contentrewards.com/articles/gta-6-clipping) · [Clip streamers guide](https://contentrewards.com/articles/get-paid-clip-streamers) · [Streams Charts GTA 6](https://streamscharts.com/specials/gta6) · [Rockstar video policy](https://support.rockstargames.com/articles/7bNaeoMFTV0iUDGhStTXvz/policy-on-posting-copyrighted-material) · [Rockstar spoiler rule coverage](https://ixbt.games/en/news/2026/11/04/spoilerit-siuzet-gta-vi-zapreshheno-daze-posle-reliza-igroki-zametili-pravila-rockstar-pozvoliaiushhie-udaliat-zapisi.html) · [YouTube gaming violence ad rules](https://respawn.outlookindia.com/gaming/gaming-news/youtube-updates-gaming-violence-ad-rules-ahead-of-gta-6) · [YouTube reused content](https://support.google.com/youtube/answer/1311392) · [TikTok Direct Post API](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post) · repos linked in section 2
