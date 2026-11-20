# Hype detection research

Research date: 2026-11-20. Recommendation: test independent audio candidates plus transcript selection before further chat tuning. No external result establishes 60% viewer-clip recall for sparse KreekCraft chat.

## Sources and methods

Stars below are GitHub's displayed counts, sometimes rounded, observed through web fetches. U = unverified. Last commit is U unless explicitly qualified: GitHub root pages omit dates, several history fetches failed, and accessible histories were stale. Project descriptions are documented behavior, not independently reproduced results. “No benchmark found” means none in the opened documentation; it does not establish that none exists.

| Project/paper and source | License; stars; last commit | Signals, scoring, thresholds/merging | Evaluation and useful idea |
|---|---|---|---|
| [TwitchSnipBot](https://github.com/bihanikeshav/TwitchSnipBot) | No license visible; 2; U | Rolling message-rate z-score; also LSTM highlight/category heads, statistical bootstrap labels. Exact thresholds/merging U. | No benchmark found. Distinguish learning human highlights from merely learning the spike heuristic. Ideas only. |
| [auto-clipper-ML](https://github.com/JonasBuffington/auto-clipper-ML) | No license visible; 1; U | 30-second windows, 12 velocity/sentiment/emote/engagement features; streamer-specific Random Forest, ranked predictions. Threshold/merging U. | README reports ~9% precision/~2% recall at its chosen threshold, viewer-created clips as labels, 30+ VODs of one comedy streamer. Split protocol U. Relevant warning about sparse chat; no code reuse. |
| [artkulak detector](https://github.com/artkulak/twitch-stream-highlights-detection) | Unlicense; 59; U | Audio tags, transformer chat sentiment, motion; 10-second features fused by logistic regression into highlight probability. Threshold/merging U. | No numerical benchmark/ground-truth protocol found in README. Lightweight learned fusion is reusable as an idea; dependencies/weights need separate license checks. |
| [auto-highlighter](https://github.com/porplax/auto-highlighter) | No license visible; 4; U | Audio loudness; README's default threshold is labeled 85 dB, adjustable per recording. Merging U; measurement convention not verified. | No benchmark found. Try relative loudness rather than transplanting an unexplained absolute threshold. Ideas only. |
| [OpenShorts](https://github.com/mutonby/openshorts) | [MIT](https://raw.githubusercontent.com/mutonby/openshorts/main/LICENSE), excluding `cloud/` per our rules; 9.4k; U | LLM ranks transcript plus scene boundaries; 3–15 picks, 15–60 seconds, virality scores. Merge policy U. | No viewer-clip benchmark found. Permissive starting point for transcript selection outside `cloud/`; score is not demonstrated accuracy. |
| [clipper-skill](https://github.com/RealAdii/clipper-skill) | MIT; 12; U | Claude reads the whole Whisper transcript, selects complete ideas; word-aligned cuts and first/last-five-second retranscription QA. No numerical highlight threshold documented. | Interview examples, no detection benchmark. Reuse editorial workflow; boundary QA does not validate highlight quality. |
| [hotclip](https://github.com/xixihhhh/hotclip), [method description](https://github.com/xixihhhh/hotclip/blob/main/docs/en.html) | AGPL-3.0; 497; U | Chat density, paid interactions, per-sender caps/surge bonuses; loudness, cuts, motion, facial emotion, laughter alternatives. Exact fusion/merge U. | No benchmark found. Independent evidence channels are useful ideas; copy no code. |
| [Clips Kitty](https://github.com/ColinGPT9/clips-studio) | AGPL-3.0; 486; U | Per-video normalized audio/visual/reaction signals in one-second bins; capped audience bonus; LLM transcript scoring and finalist comparison. Exact merge U. | Hardware/demo claims, no ground-truth accuracy benchmark found. Relative finalist comparison is an idea only. |
| [gta6-stream-clipper](https://github.com/vanz-0/gta6-stream-clipper) | U; stars U; date U | Repository fetch failed; method U. | PLAN calls it ideas-only. No independently verified reusable material. |
| [SupoClip](https://github.com/FujiwaraChoki/supoclip) | [Noncommercial Source License v1.1](https://raw.githubusercontent.com/FujiwaraChoki/supoclip/main/LICENSE); 3.7k; U | LLM selects 3–7 transcript segments; hook/engagement/value/shareability scores. Automatic merging U. | No benchmark found. License file differs from website AGPL wording; retain repo prohibition on reuse. |
| [Fu et al., EMNLP 2017](https://aclanthology.org/D17-1102.pdf) | Paper; implementation license U; stars/date N/A | Character-level chat CNN/RNN plus visual CNN/LSTM; fan-highlight alignment provides labels. Last quarter of clips used as positive training frames in preferred setting. | Test F-scores: chat 43.2/39.7, video 72.2/69.2, fusion 74.7/70.0 (English/Chinese LoL). Frame classification against fan compilations, not our top-15 recall. |
| [Ringer & Nicolaou, 2018](https://research.gold.ac.uk/24109/1/deep-unsupervised-multiGRO.pdf) | Paper; code license U; stars/date N/A | **Not chat-based:** face/game reconstruction novelty plus speech-band audio, recurrent fusion; highest-error 0.01% frames, link overlapping events, 10 seconds before/5 after. | Authors label 75/98 generated clips interesting across 11 PUBG games/two streamers. Selected-clip precision, not recall of all highlights. |
| [Lightor, ICDE 2020](https://www.microsoft.com/en-us/research/wp-content/uploads/2020/02/icde20lightor.pdf) | Paper; code license U; stars/date N/A | Logistic regression over message count, length, similarity; suppress overlapping windows, separate top-k, shift for reaction delay; refine using playback interactions. | MTurk evaluation; initializer trained on one Dota2 video, tested on seven. Distinguishes chat precision from video boundary precision; playback refinement needs interactions we lack. |

Accessible history snapshots only: [OpenShorts](https://github.com/mutonby/openshorts/commits/main/) ends September 10, [hotclip](https://github.com/xixihhhh/hotclip/commits/main/) September 5, [Clips Kitty](https://github.com/ColinGPT9/clips-studio/commits/main/) September 10, [SupoClip](https://github.com/FujiwaraChoki/supoclip/commits/main/) July 11, all 2026. These are **not verified current last commits**.

## Implications for our data

Fu's ablation supports combining signals, not promising transferable accuracy. Ringer's authors also identify game-audio contamination: loud gunfire can trigger novelty without a compelling streamer reaction. Lightor shows why message content/repetition and reaction-delay correction matter beyond volume. None demonstrates a universal sparse-chat accuracy ceiling.

Read-only sanity check: Python standard-library JSON/Counter analysis of the six aligned cached `chat.json` files, 1,080 ten-second bins each, named users only; no detector tuning or API calls. Results:

| Hours | Messages/s | Median messages/bin | Bins passing current three-user/maximum-half-share gate |
|---|---:|---:|---:|
| 0–3 | .741 | 4 | 67.1% |
| 3–6 | .777 | 4 | 69.9% |
| 6–9 | .759 | 4 | 72.7% |
| 9–12 | .784 | 4 | 69.7% |
| 12–15 | .550 | 3 | 57.4% |
| 15–18 | .392 | 2 | 40.9% |

Inference: low counts make rate and emote proportions unstable; longer bins improve stability but blur timing. Gate rejection is not an accuracy ceiling, since neighboring bins can still nominate a moment. Chat cannot reveal an event that produces no distinctive audience response. Existing [STATUS](../STATUS.md) reports ~30% strict/33% overlap versus ~22% chance, and acknowledges defaults were selected after inspecting held-out results: use fresh VODs next.

## Ranked next experiments

Expected gains below are hypotheses, not measured percentage-point forecasts. Runtime estimates are qualitative unless attributed to STATUS.

1. **Independent audio candidates, then fuse with chat.** Highest plausible recall gain: recover reactions without chat spikes. Compare existing RMS spikes with speech-band energy; manually inspect laughter/shouts versus game explosions. CPU decoding, bounded memory, no GPU required; throughput unmeasured. Existing MIT project code suffices; no external detector port needed. Laughter model code/weight licensing remains U.
2. **Transcript-wide candidates plus LLM finalist ranking.** Likely improve semantic relevance and quiet-moment recall; ranking only existing hype windows cannot recover excluded events. Adapt MIT clipper-skill/OpenShorts workflows. STATUS measured ~30 minutes transcription per three hours on this GTX 1060; cached transcripts avoid that. Local quantized LLM speed/fit unverified; compare small batches through the existing selection workflow, no new account.
3. **Per-streamer logistic/GBM model after collecting more labeled VODs.** Possible modest ranking gain, high overfitting risk with six slices from one day. Use counts, unique users, emote ratios, repetition/length, lagged features and audio; split by entire VOD. CPU training/inference should be inexpensive at this scale; labeling dominates. Independently implement; auto-clipper-ML has no verified reuse license. GBM performance here is unverified.
4. **Viewer-clip clusters as an optional prior.** Strong practical retrieval aid where clips already exist; negligible CPU from cached metadata. Existing MIT code supports it. Never score against the same clips used as input: report this mode separately against independently annotated moments. No credentials needed for cached-only experiments.

## Acceptance recommendation and limitations

Retain 60% as a multimodal aspiration; current evidence does not justify it as a chat-only requirement, nor prove it impossible. Preserve the existing viewer-clip test for continuity, explicitly calling it recall of top-viewed clip starts/spans at fixed 15-window budget and 30-second tolerance. Also report duration coverage, matched random baselines, deduplicated events, per-VOD uncertainty and human-reviewed precision. Viewer clips are incomplete positives; low-view selections and duplicate moments weaken the target.

Add a separate blinded human-labeled sample including quiet periods. LLM-judged recall can supplement it only with a frozen independent judge and human agreement audit; it should not replace a failed metric or grade its own selections.

`gh search repos`, `gh search code` and `gh api` were attempted but blocked by the network proxy; web search/fetch substituted. GTA6 repo, several raw files/history pages and API metadata were inaccessible; current commit dates, most implementation thresholds, GBM-on-viewer-clips evidence and external benchmarks could not be verified. No code copied, dependencies installed, secrets accessed or production files changed. Explicit task scope overrides CLAUDE's routine STATUS update.
