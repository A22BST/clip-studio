# gta6-clipper vs. our pipeline: pros and cons (21 Nov 2026)

## Where gta6-clipper is stronger
- **A finished app.** It has a review screen (A approves, X rejects), "ask for a new version", a style tab, your own voice line on a clip, auto-scheduling, and a daily 9:00 run. We have none of these.
- **Live moments.** It records the stream live and cuts a clip about 11 seconds after chat explodes. We only work from finished VODs, so it can post sooner, while the moment is still hot.
- **Free models already work.** It runs with no AI, or with Codex, Gemini, Kimi or a local model, which matches your free-model research. Ours still calls Claude; the free-model plan in `STATUS.md` is decided but not built.
- **It checks itself.** Each short is marked pass, warn or fail, and it learns from YouTube view stats.

## Where gta6-clipper is weaker or risky
- **No license.** We can't copy its code, and the author can change it or take it down at any time. We'd depend on one stranger.
- **It updates itself.** It pulls new code from GitHub every 5 hours, and nobody checks that code before it runs on your PC. Self-update would have to be turned off.
- **It doesn't know our campaign rules:**
  - it clips any GTA 6 streamer, and we may only clip campaign streamers;
  - no KreekCraft overlay;
  - no `#ad` or required hashtags;
  - no spoiler rule;
  - no Content Rewards timing.
- **Paid posting.** It posts through Blotato, a paid plan sold through an affiliate link. We already built Upload-Post with the safe posting pace.
- **Unproven on your laptop.** The author made 10 shorts in 28 minutes on their own PC. We don't know what it does on a GTX 1060 with 16 GB RAM.
- **Two pipelines to maintain.**

## Where ours is stronger
Campaign rules, safe auto-posting, the KreekCraft overlay, your unique-moment clip bar, 807 tests, and an MIT license, so the code is fully ours.

## Recommendation
Run one cheap trial on a single KreekCraft VOD:
1. Codex checks the zip for anything unsafe.
2. Install it in its own folder outside our repo, with self-update off.
3. Run it in no-AI or Codex mode, which uses no Claude tokens.
4. Compare its clips with ours against the unique-moment bar.

If its clips win, rebuild its best parts in our code: live chat-spike catching, the review app and the voice line. The free-model chain for both comes from your research. If ours win, keep its ideas only.
