# Free tools and free AI for Clip Studio: ranked shortlist (21 Nov 2026)

Research only. Nothing was installed, signed up for, downloaded or run. All facts were read from vendor and repo pages on
**2026-11-21** by three Codex research passes (gpt-6.1-sol, medium) and then read through by the author of this note; the author
did **not** independently re-open the sources, so treat every limit below as "checked once, same day" and re-check the one you
are about to depend on. "U" or "unverified" means the pages opened did not settle it. Scores (1-5) and verdicts are judgments, not
benchmarks. No speed, VRAM or accuracy number for the GTX 1060 was measured by anyone: every GPU/RAM figure marked "E" is an
estimate. Full per-candidate tables with every URL are kept outside the repo (see "Raw parts" at the end).

License rule used: MIT / Apache-2.0 / BSD / ISC / CC0 / OFL (fonts) = usable as code or asset. AGPL, GPL (as linked code),
noncommercial, custom "community" licences and "no licence found" = ideas only. LGPL/GPL tools (FFmpeg, aubio) are fine as
separate CLI processes. A repo's code licence is not a licence for its downloadable model weights: both are listed where known.

## 1. What is new versus what we already have

Already covered, so not re-researched: free-model chain (Z.ai, NVIDIA NIM, OpenRouter, Google AI Studio, Cloudflare, Groq, AIHubMix,
Pollinations, Ollama); faster-whisper large-v3-turbo + WhisperX; MediaPipe/OpenCV facecam; ASS captions (4 presets); chat-rate hype
(`hype.py`, already with user-share and emote caps); `audio_hype.py` loudness DSP; transcript hype; Twitch viewer clips as
candidates; cut-point QA; `dark_opening` warning; SFX source licensing review and the cleared 25-sound pack; music OFF; quso /
repurpose.io (rejected); Upload-Post as poster; gta6-clipper and its siblings (ideas only).

New in this note: a free **vision judge**; audio **event tagging** (laugh/scream/shout) as a candidate source; an **ASR offload**;
**finished-media QC with named ffmpeg filters** (virality items #6, #13, #14 exist as plans; this note names concrete tools);
CPU rerank prefilter; free official analytics APIs; a check of every other free LLM API (almost all are dead or need a card).

**One finding that changes priorities.** The selection comparison (STATUS) showed a *ceiling*: only 30% (Day 2) and 50% (Day 3) of
the top-10 viewer clips fall inside any candidate window at all, and the fused-hype test peaked at 45%. So the weak point is
**candidate recall**, not the LLM picking step. Tools that add *new, independent candidate sources* (audio reaction tags, visual
event cues) and a *judge that looks at the footage* help more than adding another text LLM to the chain.

## 2. Top-10 shortlist

Ranked by expected value for "find unique/weird/crash-out moments and ship clean clips" divided by effort. "Trial" = run one small
controlled test, not adopt.

| # | Candidate | Stage and where it plugs in | Licence (code / weights) | Free limits and cost | GPU / RAM on the laptop | Setup | Value | Verdict | Primary source (checked 21 Nov) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **ffmpeg `blackdetect` + `freezedetect` + `silencedetect`, ffprobe export contract, `loudnorm` measure** | Finished-clip QC, after render: black / frozen / silent stretches anywhere in the clip (not only the opening), 9:16 + 20-60 s + stream checks. Fixes the Day 4 tiger case (8 s black Wasted screen scored QA 90). Already planned as virality #14; this names the tools. | LGPL-2.1+ (build may be GPL); **run as CLI only** | Free, no key | CPU only, ~1 GB RAM; no model | S (no install) | 5 | **TRIAL first.** Warn, never auto-reject on silence alone; run freeze check on the gameplay crop, because moving captions hide a frozen picture | [filters](https://ffmpeg.org/ffmpeg-filters.html#blackdetect), [licence](https://ffmpeg.org/legal.html) |
| 2 | **Hosted vision judge: Gemini on the existing Google bucket** (`gemini-3.8-flash` as baseline, new ID `gemini-4-hydrogen` to A/B) | Selection: after candidates are scored, send 5-15 s clip or 3-6 ordered frames + transcript and ask a JSON question ("what visibly happens; is it weird / shock / crash-out; unusualness 0-5; evidence frames"). Also gives the hook a *visible* event to describe. | Proprietary API terms | Free standard tier; 1,048,576-token context; video via Files API (2 GB) or inline (<100 MB). Exact RPM/RPD is per project and not public (U): read it in AI Studio. Rough token cost (my estimate): 10 s clip about 3k tokens, 30 windows per 3 h slice about 100k tokens. EEA: Part B found wording that paid-tier data protection applies to unpaid quota for EEA users and that content is not used to improve products; STATUS had flagged this as unfound, so re-read aistudio.google.com/docs/terms once | None (cloud) | S (new model ID in the existing bucket + a frame/clip uploader) | 5 | **TRIAL.** Default video sampling is 1 fps, so very short glitches can be missed: send denser frames around the peak | [Hydrogen](https://aistudio.google.com/docs/models/gemini-4-hydrogen), [Flash 3.8](https://aistudio.google.com/docs/models/gemini-3.8-flash), [video](https://aistudio.google.com/docs/video-understanding), [terms](https://aistudio.google.com/docs/terms) |
| 3 | **Local vision judge: Qwen3-VL-2B-Instruct Q4_K_M + projector via llama.cpp** (compare SmolVLM2-2.2B) | Same judge step, offline fallback when hosted quotas are spent. Run only when Whisper and render are idle. | Apache-2.0 weights (commercial yes); llama.cpp MIT | Free; official GGUF 1.11 GB + 445 MB projector | E: 2.5-4 GB VRAM, 4-7 GB RAM; GTX 1060 speed **unmeasured** | M (llama.cpp Windows CUDA/Vulkan build, one model download) | 4 | **TRIAL after #2.** If a frame takes more than ~20 s on the 1060 it is not worth it; then keep it CPU/overnight only | [model](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct), [GGUF files](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/tree/main), [llama.cpp multimodal](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md) |
| 4 | **Audio event tagging: CLAP (HTSAT-unfused) or YAMNet** on shortlisted windows | Candidates: score each hype window (and a sparse scan of the rest) for laughter / scream / shout / gasp. Independent of chat, extends `audio_hype.py` and virality #13 (voice_jump). Tells rage from loud game audio better than loudness alone. | CLAP repo CC0-1.0, checkpoint card Apache-2.0; YAMNet code Apache-2.0 but hosted checkpoint licence **unverified** | Free local | CPU is enough (budget 2-4 GB RAM); CLAP weight file 615 MB; GPU not needed | M (PyTorch/Transformers or TensorFlow; TF on native Windows is CPU-only) | 4 (potential) | **TRIAL CLAP first** (clear licences); YAMNet only after its checkpoint terms are pinned. Cannot tell streamer from game audio, so use as a feature next to speech-activity, not alone. CLAP repo last commit 2025-05 (stale but works) | [CLAP](https://github.com/LAION-AI/CLAP), [checkpoint](https://huggingface.co/laion/clap-htsat-unfused), [YAMNet](https://github.com/tensorflow/models/tree/master/research/audioset/yamnet) |
| 5 | **Opening-frame picker from cheap image stats** (OpenCV brightness coverage + Laplacian sharpness + existing face-box visibility; ffmpeg `thumbnail` for a representative frame) | Render: choose or trim to the earliest informative frame (<=2 s), thumbnail from a later reaction frame. Virality #6; this is the recipe. | OpenCV Apache-2.0; Pillow MIT-CMU; ffmpeg CLI | Free, existing deps | CPU, ~0.5 GB | S | 4 | **TRIAL.** Score gameplay and facecam regions separately so a bright caption cannot hide a dark picture; never reorder the video for a thumbnail | [Laplacian](https://docs.opencv.org/4.13.0/d5/db5/tutorial_laplace_operator.html), [thumbnail filter](https://ffmpeg.org/ffmpeg-filters.html#thumbnail) |
| 6 | **Own ASS caption upgrades + OFL font bundle** (karaoke `\k`, timed `\t` scale pop, bold condensed fonts Anton / Barlow Condensed) | Render: captions. Extends the 4 presets; no new dependency. | libass ISC; fonts SIL OFL-1.1 (keep OFL notices) | Free | CPU; no model | S | 3-4 | **TRIAL** with a phone-size legibility check; bundle the font files instead of relying on system fallback. Windows colour-emoji in libass is **unverified**: do not promise it | [ASS tags](https://aegisub.org/docs/latest/ass_tags/), [Anton OFL](https://raw.githubusercontent.com/google/fonts/main/ofl/anton/OFL.txt) |
| 7 | **Chat/clip signal extensions** (own code): emote *type* mix + distinct reactors per bucket; distinct creators of viewer clips near a VOD offset | Candidates: small add to `hype.py` and the viewer-clip candidates. | Own code (Twitch data terms apply) | Free, existing exports | CPU, <0.5 GB | S | 3 | **TRIAL, small.** Part of this exists (`min_users`, `max_user_share`, `emote_cap`); the new bit is *distinct clip creators* and emote types. Use `video_id` + `vod_offset` (not `created_at`), drop null offsets | [Get Clips](https://dev.twitch.tv/docs/api/reference/clips/#get-clips), [chat messages](https://dev.twitch.tv/docs/chat/send-receive-messages) |
| 8 | **CPU rerank prefilter: multilingual-e5-small (MIT) + bge-reranker-v2-m3 (Apache-2.0)** | Selection: cut the candidate list before the LLM/vision judge; query = the "weird / crash-out" bar in words. Replaces the earlier "nemotron rerank" idea with a local, no-quota option. | MIT / Apache-2.0 | Free local | E: e5-small 1-2 GB RAM, bge-reranker 3-5 GB RAM FP32 (1.5-3 GB int8); CPU | M | 3 | **TRIAL**, but measure recall on the viewer-clip ground truth first: relevance to a text query is not virality, and the ceiling problem is recall, not ordering | [e5-small](https://huggingface.co/intfloat/multilingual-e5-small), [bge-reranker](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| 9 | **Official free analytics APIs for the learning loop: YouTube Analytics API, Instagram Media Insights, TikTok Display API** | Analytics: per-video views, and (YouTube) watch time/retention that Upload-Post may not expose. Feeds `learn.py` / `what_works.md`. | Service terms (not code licences) | Free; OAuth per account; Instagram metrics lag ~48 h; TikTok Display 600 req/min per endpoint; per-project YouTube Analytics quota U | none | M-L (Ahmad must create OAuth apps; "ask before creating any account/key" rule applies) | 3-4 | **WATCH until week 1 data exists.** First check what Upload-Post analytics returns live; add YouTube Analytics only if retention is missing. Public view counts are not proof of Whop-qualifying views | [YouTube Analytics](https://developers.google.com/youtube/analytics/reference/reports/query), [IG Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights), [TikTok Display](https://developers.tiktok.com/docs/en/display-api-overview) |
| 10 | **GTA HUD banner detection by our own OpenCV template matching** (WASTED / BUSTED / mission-passed ROIs; Tesseract or RapidOCR only as a second opinion) | Candidates + QC: a "wasted" banner marks both a likely funny death and a dead-footage risk (Day 4). | OpenCV Apache-2.0; Tesseract Apache-2.0; RapidOCR Apache-2.0 (pin the model file's own licence) | Free | CPU, ~0.5-2 GB | M (we must cut our own templates from GTA 6 frames; no ready GTA 6 dataset exists) | 3 | **TRIAL late.** The black-frame QC (#1) already catches the dead-footage half. The existing GTA detector found (streamclipper) is AGPL with only a GTA V profile: ideas only | [template matching](https://docs.opencv.org/4.13.0/d4/dc6/tutorial_py_template_matching.html), [RapidOCR](https://github.com/RapidAI/RapidOCR) |

Runners-up (value 3, worth doing only when the above are done):
- **Groq `whisper-large-v3-turbo` as ASR offload/fallback** on the key we already have: published row 20 RPM, 2,000 RPD, 7,200 audio-s/hour, 28,800 audio-s/day (8 h/day), 25 MB free upload (chunk and compress). Same model as local, so no quality gain. Because of the 7,200 s/hour cap a 3 h slice takes about 1.5 h, so it is *not* faster than the local ~30 min; use it when the GPU is busy or Whisper hits `MemoryError`. [Groq limits](https://console.groq.com/docs/rate-limits), checked 21 Nov.
- **Qwen3-4B-Instruct-2507 Q4 (Apache-2.0, ~2.5 GB)** as a better local last-resort in the Ollama slot; compare against what Ollama has today. E: 3.2-4.5 GB VRAM. [model](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507).
- **PySceneDetect AdaptiveDetector** (BSD-3, v0.7.3) for shot-change times to snap cut points and add visual-change cues; a cut alone is not a unique moment. [repo](https://github.com/Breakthrough/PySceneDetect).
- **DeepFilterNet** (MIT or Apache-2.0 incl. weights) mic denoise before transcription or on the clip; try on a few noisy clips; GTX 1060 cost unmeasured. [repo](https://github.com/Rikorose/DeepFilterNet).
- **ctc-forced-aligner + wav2vec2-base-960h** (BSD-2 / Apache-2.0) for word timing, only if cut-point QA shows caption-timing errors that WhisperX does not fix. Its *default* MMS checkpoint is CC-BY-NC: never use it. [repo](https://github.com/MahmoudAshraf97/ctc-forced-aligner).
- **YuNet** (OpenCV Zoo, MIT, 227 KB ONNX) as a fallback face detector only for clips where the current detector finds nothing. [model](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet).

## 3. Recommended first trial per pipeline stage

| Stage | First trial | Why this one | Done when |
|---|---|---|---|
| Moment finding: audio | CLAP prompts ("person laughing", "screaming", "shouting angrily", "gasping") on the top-30 hype windows of the Day 2 and Day 3 jobs | Independent of chat; extends voice_jump | Tags per window saved; do the tagged windows overlap the viewer clips and your own "weird" labels better than loudness alone? |
| Moment finding: visual / game events | Gemini frame-judge (#2) on the same windows; OpenCV motion energy as a free side feature | Needs no GTA 6 templates | Judge output per window; compare against viewer-clip ground truth and human labels |
| Moment finding: chat / clip | Add distinct clip creators + emote types to existing scoring | Cheap, extends `hype.py` | Hit rate on the held-out slices does not drop |
| Transcription | Keep faster-whisper. Only add Groq Whisper as a fallback route | No verified better model on this hardware | Fallback triggers on MemoryError/GPU-busy |
| Captions | ASS `\t` pop + Anton / Barlow Condensed on 3 clips | Zero new dependencies | Phone-size frame check passes |
| Reframing / face tracking | None needed. Keep current detector; YuNet only for clips where it fails | Facecam is a fixed corner webcam | Detector-miss rate on a batch is the trigger |
| Thumbnail / opening frame | OpenCV brightness + sharpness + face-visible score per candidate start (#5) | Fixes dark opens | `dark_opening` warnings drop to 0 on an 8-clip batch |
| Finished-media QC | ffmpeg black/freeze/silence + ffprobe contract (#1) | Real failure already seen | The Day 4 tiger clip is flagged |
| Sound / music | Nothing new. Optional: jsfxr (Unlicense) or ffmpeg-synthesised stings if the 25-pack runs thin | Original sounds carry no licence risk | n/a |
| Hooks / titles | Make the **vision judge describe the visible event** and feed that to the chain for the hook; no new library | Hooks that match the footage; no external dataset is permissively licensed and tied to performance | Hook mentions only things the judge saw |
| LLM chain | Add `gemini-4-hydrogen` as a model in the Google bucket; nothing else (see section 4) | Only verified free addition | Appears in `autoclip config chain`, one live call OK |
| Vision | Hosted Gemini first, local Qwen3-VL-2B second | See #2, #3 | Same prompt, same 30 windows, both compared |
| Posting / analytics | Keep Upload-Post. Test what its analytics return; add YouTube Analytics only if retention is missing | Direct APIs need public media URLs or app audits | One week of per-post numbers in the tracker |

## 4. Free LLM and multimodal services (beyond the existing chain)

**Verdict: no new recurring, no-card, production-grade hosted LLM provider was found.** Most free offers are gone or need a card.
Sources, 21 Nov: [GitHub Models retired 30 Jul 2026](https://docs.github.com/en/github-models); [Mistral current limits](https://docs.mistral.ai/admin/billing-usage/usage-limits) (Free mode excludes API); [Hugging Face pricing](https://huggingface.co/docs/inference-providers/pricing) (no free credits listed).

| Name | Plugs in as | Licence / terms | Free limit | Setup | Value | Verdict |
|---|---|---|---|---|---|---|
| `gemini-4-hydrogen` (existing Google bucket) | selection + vision + audio | proprietary API | free standard tier, 1,048,576 ctx, 65,536 max output; quotas per project (U) | S | 5 | **TRIAL** (see #2) |
| Existing Groq `qwen/qwen3.8-27b` with images | tiny 3-frame judge | model licence U | 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD; 3 images/request at ~2,048 tokens each, so 3 frames eat ~6,144 of the 8,000 TPM | S | 3 | **WATCH**; only for tiny prompts |
| Existing OpenRouter `nemotron-3.5-super-vl:free` | gameplay-only frame judge | NVIDIA terms | 1M ctx, 20 RPM, 50 RPD | S | 3 | **WATCH**: the endpoint logs prompts and says not to upload faces/voices, so never send facecam frames |
| Existing Cloudflare `@cf/google/gemma-4-26b-a4b-it` (vision) and `@cf/openai/whisper-large-v3-turbo` | frame judge / ASR | Gemma 4 E2B card is Apache-2.0 (other Gemma 3 / 3n / PaliGemma use Gemma terms) | shared 10,000 neurons/day; Whisper about 46.6 neurons/min so at most ~3.6 h/day if nothing else uses the budget | S | 3 | **WATCH**: shares the budget with chain traffic |
| Public AI (`swiss-ai/apertus-v1.5-8b`) | extra provider, text + image | Apache-2.0 weights; gateway terms research/education, commercial use U | **$2 once**, 100 RPM; 262K ctx | S | 2 | **WATCH**: finite credit |
| Deepgram Nova-3 | ASR emergency reserve | proprietary | **$200 once**, no card, ~700+ h total; training on by default (opt out with `mip_opt_out=true`) | S | 3 | **WATCH** |
| AssemblyAI | ASR reserve | proprietary | $50 once, ~185 h; free users cannot opt out of training | S | 2 | **SKIP** unless content may be trained on |
| AI21 Jamba, Cohere (trial), LLM7, Puter.js, Reka | evaluation only | evaluation / noncommercial / research terms | 1,000 calls/month (Cohere), $10 for 7 days (AI21), etc. | S | 1-2 | **SKIP** for the chain |

Local text last-resort in Ollama: **Qwen3-4B-Instruct-2507** (Apache-2.0) first, **Phi-4-mini** (MIT, ~2.5 GB) second. Do not
use Llama 3.2 or Gemma 3 as the default (custom licences, not clearly permissive); Gemma 4 E2B is Apache-2.0 per its card.

## 5. Free tools by stage (the rest of the candidates)

Only rows not already in the top 10 or runners-up. V = value 1-5. All CPU unless noted; "E" = estimate.

**Moment finding**
| Name | Licence | Notes | V | Verdict |
|---|---|---|---|---|
| OpenCV optical-flow / motion energy | Apache-2.0 | Free secondary cue; camera pans and driving need a rolling baseline | 3 | TRIAL as a side feature |
| Silero VAD | MIT | Speech mask to weight hype and keep padding around non-speech reactions; skip if faster-whisper's VAD already exposes it | 3 | WATCH |
| OpenCLIP ViT-B/32 / SigLIP2 base | MIT / Apache-2.0 | Frame-text similarity prefilter (~0.6-0.8 GB weights); no temporal reasoning | 3 | WATCH, after the VLM judge |
| X-CLIP base | MIT | Real video-text model; GTA transfer unproven | 2 | WATCH |
| VADER | MIT | Weak chat polarity; slang and sarcasm unreliable | 2 | WATCH |
| Tesseract / RapidOCR / PaddleOCR | Apache-2.0 | OCR for HUD text; pin each model file's licence | 3 | WATCH (see #10) |
| Twitch EventSub (hype train, raids, predictions), stream markers | official API | Hype-train and marker scopes need the **broadcaster's** authorization (`channel:read:hype_train`, `channel:manage:broadcast`) and a live stream; fine for a streamer who cooperates, not for third-party VODs | 2 | WATCH |
| TwitchIO | MIT | Python chat/EventSub library; only for live capture | 2 | WATCH |
| StreamElements / Streamlabs feeds | official, token needed | Creator-authorized only; do not scrape overlays | 2 | SKIP |
| TwitchTracker / SullyGnome | no reuse licence | Coarse aggregates; SullyGnome asks for no scraping | 1 | SKIP |
| PANNs, TransNetV2, emotion2vec | MIT / MIT / custom | Last commits 2021 / 2021 / 2024; emotion2vec licence unclear | 1-2 | SKIP |

**Transcription and timing**
| Name | Licence | Notes | V | Verdict |
|---|---|---|---|---|
| sherpa-onnx + Parakeet TDT 0.6B v2 int8 | Apache-2.0 runtime; weights CC-BY-4.0 (attribution) | Independent CPU ASR to cross-check cut-point QA; no evidence it beats turbo on game audio | 3 | WATCH |
| whisper.cpp | MIT | CPU fallback runtime; no verified speed/accuracy gain | 2 | WATCH |
| distil-whisper, stable-ts (archived May 2026) | MIT | Older / paused; WhisperX already covers alignment | 1-2 | SKIP |
| whisper-timestamped | AGPL root licence with GPL header | Conflicting licence | 1 | SKIP |

**Captions**
| Name | Licence | Notes | V | Verdict |
|---|---|---|---|---|
| Pillow ImageDraw to cached PNG + ffmpeg overlay | MIT-CMU | Static hook cards only; keep timed words in ASS | 3 | TRIAL for hook cards |
| OpenCut | MIT | Manual editor, no headless ASS parity | 2 | WATCH |
| MoviePy v2 | MIT | Another composition layer over ffmpeg for no gain | 2 | SKIP |
| Remotion | custom licence (not permissive; paid above 3 people) | Whole new Node/Chromium stack | 1 | SKIP |

**Reframing**
| Name | Licence | Notes | V | Verdict |
|---|---|---|---|---|
| Own smoothing (deadband, velocity limit, shot-cut resets) + OpenCV spectral-residual saliency | Apache-2.0 | Policy is our code; AutoFlip is an Apache-2.0 reference but needs OpenCV 3 | 4 | TRIAL if crop jitter shows in review |
| YOLOX nano/tiny, RT-DETR | Apache-2.0 | General object boxes, not faces; weights licences not pinned | 2 | WATCH |
| ByteTrack (association only) | MIT | Last commit 2022; little use with one fixed webcam | 2 | WATCH |
| Ultralytics YOLO, InsightFace/SCRFD weights | AGPL / noncommercial weights | | 1 | SKIP (ideas only) |

**Thumbnails and frame quality**
| Name | Licence | Notes | V | Verdict |
|---|---|---|---|---|
| LAION improved aesthetic predictor | Apache-2.0 code, checkpoint terms unverified | Photo aesthetics may fight useful reaction frames; last commit 2023 | 2 | WATCH |
| pyiqa (NIMA, CLIP-IQA) | PolyForm Noncommercial | | 1 | SKIP |
| PyAV | BSD-3 but links FFmpeg libraries | Prefer the ffmpeg CLI for sampling | 1 | SKIP |
| libvmaf | BSD-2-Patent | Only for comparing encoder settings; reframed output is not comparable with the source | 2 | WATCH |

**Sound** (the 25-pack is already cleared, so these are only extras)
| Name | Licence | Notes | V | Verdict |
|---|---|---|---|---|
| Kenney Interface Sounds (100 files) | CC0-1.0 | Clean UI-style punctuation sounds | 3 | WATCH (extra) |
| Sonniss GameAudioGDC bundles | custom GDC Bundle EULA v2.0 (effective 2026-08-27): commercial sync, no attribution, no re-supply as raw assets, no AI training | Large recorded impacts/whooshes; keep the EULA text and download date | 3 | WATCH (extra) |
| jsfxr (Unlicense), Bfxr2 (MIT), ffmpeg `aevalsrc`/`sine`/`anoisesrc` | Unlicense / MIT / CLI | Original synthesised stings, no third-party sample risk | 3 | WATCH |
| librosa (ISC) onset detection | ISC | Snap an already-chosen SFX cue to a nearby transient; not event detection | 3 | WATCH |
| pyloudnorm | MIT | Python loudness meter; ffmpeg `loudnorm` already covers it | 2 | SKIP |
| RNNoise | BSD-3 | Light denoiser; DeepFilterNet is stronger | 2 | WATCH |
| Demucs | MIT (repo archived Jan 2025) | Stem separation; docs say >=3 GB VRAM, default ~7 GB; "removes music so Content ID will not fire" is **unverified** | 2 | WATCH |
| Incompetech (CC BY 4.0, credit needed), Bensound (per-video code), Orange Free Sounds, OpenGameArt | mixed | Background music stays OFF; per-asset licence checks needed | 1-2 | SKIP |

**Hooks, titles, effects**
| Name | Licence | Notes | V | Verdict |
|---|---|---|---|---|
| Hook/title drafting by the existing chain, grounded in the vision judge's description | n/a | TikTok guidance (advertiser advice, not an organic GTA test): state the idea within 3 s, hook within 6 s | 4 | TRIAL (no new tool) |
| prompts.chat (CC0 data, MIT site), Fabric (MIT) | CC0 / MIT | Prompt-structure inspiration only; no performance-validated viral hook dataset exists under a permissive licence | 2 | SKIP |
| ffmpeg `zoompan` / crop-expression punch-ins | CLI | No evidence found that punch-ins or shakes raise views; use sparingly or A/B | 2 | WATCH |
| Twemoji (CC-BY), OpenMoji (CC BY-SA), Noto Emoji (OFL, with a README/licence mismatch for images) | mixed | Low value for gameplay shorts | 1 | SKIP |

**Scheduling and posting (official APIs only)**
| Name | Licence / terms | Free limit | Verdict |
|---|---|---|---|
| Upload-Post Basic (current) | proprietary | $24/month (STATUS) | Keep |
| Buffer Free + API | proprietary | 3 channels, 10 queued posts per channel, API 1,000 req/channel/30 days (3,000 total); key count conflicts (pricing page 5, help page 1); API needs media at a **public URL**, our clips are local files | WATCH (cannot replace Upload-Post without a free media host) |
| Metricool Free | proprietary | 1 brand, 20 posts/month, 5 competitors, 30-day analytics | WATCH for analytics only |
| Publer Free | proprietary | 3 accounts, 10 queued posts each; direct-post/API limits U | WATCH |
| YouTube Data API `videos.insert` | API ToS, OAuth | Codex read the current reference as 100 uploads/day with a separate quota bucket and **no private-only lock for unverified projects**. This contradicts the long-standing rule that unaudited API projects upload as private. **Do not rely on it**: test one upload on a new project before writing code | WATCH |
| Instagram Graph publishing (Instagram Login route) | Meta terms | 100 API posts per 24 h; no linked Facebook Page needed on this route; video must be at a public URL | WATCH |
| TikTok Content Posting API | developer terms + audit | Unaudited apps: private (SELF_ONLY) posts only; guidelines reject private single-user uploaders | SKIP |
| Postiz (AGPL-3.0, run as a separate service only), Socioboard (GPL-3.0), Mixpost Lite (MIT, but no TikTok/Instagram/YouTube), Later, Hootsuite, Typefully | various | Postiz floor 2 vCPU / 2 GB RAM and own TikTok app approval; others paid or lacking targets | SKIP |
| TikTok Research API, Threads API | | Research-only eligibility / outside our three destinations | SKIP |

## 6. Skip list (with the reason)

- **Hosted LLM/vision services that need a card or are not free:** Mistral API, GitHub Models (retired), Hugging Face Inference Providers, SambaNova (conflicting docs), Together ($5 minimum), Fireworks, DeepInfra, Chutes, Scaleway (card), Vercel AI Gateway (card), DeepSeek, Moonshot/Kimi ($1 recharge), xAI, Venice, Reka Chat, Hyperbolic, Jina API (non-commercial weights).
- **Evaluation-only free tiers (not production):** Cohere trial, AI21 trial, LLM7, Puter.js (user pays), Reka Vision.
- **Licence blockers (ideas only):** Ultralytics YOLO (AGPL), InsightFace/SCRFD weights (noncommercial), pyiqa (PolyForm NC), whisper-timestamped (AGPL), Essentia (AGPL, NC models), madmom models (CC BY-NC-SA), AudioCraft/AudioGen weights (CC BY-NC), Stable Audio Open (community licence, registration, revenue cap), Qwen2.5-VL-3B (research licence), MiniCPM-V 2.6 (registration; 7 GB), Moondream 3 (BSL), LLaVA 1.5 (Llama 2 licence), Remotion (custom), aubio (GPL, CLI only), streamclipper (AGPL), SoX synth (licence not verified).
- **Not worth the effort:** MoviePy, distil-whisper, stable-ts, ByteTrack, PyAV, VideoCLIP, PaliGemma 2 (needs fine-tuning), Gemma 3 / Llama 3.2 as defaults (custom licences).
- **Music and sound traps:** BBC Sound Effects (commercial licence not free), Epidemic Sound, Artlist trial (preview only), Meta Sound Collection (cross-platform rights unclear), meme soundboards, Bensound (per-video code), Free Music Archive, Incompetech (credit). Background music stays OFF.
- **Posting:** TikTok Content Posting API (private-only unless audited), TikTok Research API, Threads, Mixpost Lite, Socioboard, Later, Hootsuite, Typefully, Postiz (heavy, AGPL).
- **Twitch side:** TwitchTracker, SullyGnome (no scraping), StreamElements/Streamlabs scraping.
- **Live HUD clippers:** nothing to copy; no permissive GTA 6 HUD dataset exists.

## 7. Open points and cautions

1. **GTX 1060 reality:** nobody measured Qwen3-VL-2B, CLAP, or any other model on this laptop. The 6 GB card is shared with Whisper and the encoder: judge models must run when nothing else does, and all "E" memory numbers are estimates.
2. **Google terms:** re-read the AI Studio terms page once before putting more traffic on the Google bucket (EEA wording vs the earlier STATUS note), and read the real per-project quota in AI Studio.
3. **YouTube upload rule** (section 5) and the Buffer API key count conflict are unresolved contradictions in the sources.
4. **Ceiling effect:** a smarter judge cannot recover moments that were never candidates. Measure the candidate ceiling on the viewer-clip ground truth before and after adding audio tags and visual cues.
5. **Unverified on purpose:** whether adding SFX, punch-ins, or music raises views (no causal evidence found anywhere); whether removing music with Demucs reduces Content ID risk.
6. Free tiers change often. Every row is valid for 2026-11-21 only.

## 8. Raw parts

The three full research parts (about 160 KB, every candidate with all sources and the "could not verify" lists) are in the notes folder, not the
repo: `C:\Users\ahmad\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\side-session-notes\local_535fa1df-006e-48d6-9a16-70b514beaac4\`
- `A-pipeline-tools.md` (moment finding, transcription, captions, reframing, frames, QC)
- `B-free-ai.md` (free LLM, vision, local models, rerank, ASR, rejected list)
- `C-sound-posting.md` (sound, hooks, scheduling and official APIs, Twitch signals)
