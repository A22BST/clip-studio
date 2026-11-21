# Handover: free-model chain (21 Nov 2026)

For the clip-studio master session. Written from the CoWorkOS chat that planned this work. Details live in `STATUS.md` on the
branch, sections "Free-model plan", "Free-model sources" and "Free-model chain".

## Ahmad's decisions
- The clip farm runs on FREE LLMs by default, so Claude and Codex stay free for real work. Pay for premium models only once clips
  earn money.
- Goal: as many clips as possible.
- Use ALL working free models, weaker ones included: they are free capacity. Comparisons only set the ORDER, never remove a model.
- Big "heavy" models are fine for light work.
- Claude is OFF in the chain: an opt-in switch, never a silent fallback.
- Keep the current order, start using it, note how each model's clips do, and change the order from real results.
- Delegate coding to Codex (gpt-6.1-sol, medium) to save tokens. Sessions review its diffs and run the tests.

## State
- Branch `claude/free-model-chain-0660c4`, head `7249ac4`. NOT merged into `main`, NOT pushed. It already contains
  `claude/key-setup-751319`.
- Branched from `dc8e331`. `main` is 13 commits ahead (story check, SFX layer and others). The only file changed on both is
  `STATUS.md`, so expect one easy conflict there.
- What the branch does:
  - `providers/chain.py`: provider buckets (one account each) with an ordered model list and daily budgets per provider
    (`<auto_dir>/chain-usage.json`). Failover runs model to model, then bucket to bucket.
  - `auto/learn.py` (weekly report) and `auto/select.py` (clip picking) both default to `backend = chain`. `claude` is a config
    switch. The chain path has no tools: the code inlines `candidates.json`, `what_works.md`, the campaign yaml and the /clip skill
    text, then writes `highlights.json` itself.
  - The provider and model are saved per clip (DB row and tracker CSV), next to views and earnings.
  - `scripts/selection_compare.py` (`--jobs`, `--claude`, ceiling) scores models against viewer clips.
  - `autoclip config set-secret NAME --clipboard`, and `autoclip config chain` (keys, usage today).
- Keys in the keyring, all live-tested: `openrouter-free`, `google-ai-studio`, `zai-glm-flash`, `nvidia-nim`, `groq`,
  `cloudflare-workers-ai` + `cloudflare-account-id`. No key for AIHubMix or Pollinations (both need payment).
- Also done 21 Nov: `claude` CLI logged in (`find_claude()` works; not on PATH, which does not matter), and the Twitch Client
  Secret was reset (User env). Both are recorded on `main` in commit `069f8c6`.

## First live comparison (2 jobs: small sample)
| Model | Day 2 (job 05a6, max possible 30%) | Day 3 (job 11f5, max possible 50%) |
|---|---|---|
| Claude sonnet | 0% / 0% | 20% / 40% |
| gemini-3.6-flash | 0% / 0% | 40% / 60% |
| nemotron-3-ultra-550b (OpenRouter) | 0% / 0% | 30% / 38% |
| gpt-oss-120b (Cloudflare) | 0% / 0% | 20% / 40% |
| gemini-3.5-flash-lite | 0% / 0% | 20% / 100% (2 picks) |
| gpt-oss-20b (Cloudflare) | 10% / 20% | 0% / 0% |

Recall / precision against the top-10 viewer clips; "max possible" is the share of those clips that fall inside any candidate
window. Current order: gemini-3.6-flash, gpt-oss-120b, nemotron-3-ultra, gemini-3.5-flash-lite, nemotron-3.5-super-vl,
gpt-oss-20b, then the rest, with Groq last.

## Known limits
- Groq free tier is 8K tokens/min, which is too small for selection prompts. Groq only serves small prompts such as the weekly report.
- Free models fail some calls (rate limits, overload, empty replies). The chain moves on, but if EVERY model fails, that job's
  selection fails and waits for the next tick (no Claude fallback).
- OpenRouter: one shared allowance for all `:free` models, 50 calls/day (1,000/day after a one-time $10 credit; Ahmad's call).
- Google free-tier data may be used to improve Google products (public stream content, so acceptable).
- Free tiers change often. Re-check presets when a model starts returning 404/410.

## Next steps
1. Merge `claude/free-model-chain-0660c4` into `main` (resolve the `STATUS.md` conflict). Ahmad's yes is needed for the merge.
2. Run the full test suite after the merge. The last full run on the branch was 879 pass, 4 fail; 3 were fixed afterwards, and the
   4th is the clock test that `main` fixed in `2694917`. Check that the free chain still works with main's new story check.
3. Run one `clip-auto tick --dry-run` on a real job to prove the free chain end to end without posting.
4. Weekly: look at views and earnings per provider/model in the tracker and reorder `chain.entries`. Rerun `selection_compare.py
   --jobs ... --claude` when new prepared jobs exist.
