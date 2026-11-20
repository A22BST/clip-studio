# STATUS

## Build session 1 (started 2026-11-20): IN PROGRESS
Test source: KreekCraft "GTA 6 LIVE (FULL GAME) ALL ENDINGS | DAY 2" (Twitch VOD 2933758895, picked by
Ahmad's setup helper). Campaign: KreekCraft GTA 6 Clipping (`campaigns/kreekcraft-gta6.yaml`).

- [x] Fork `artbyjazi/autoclip` -> `A22BST/clip-studio` (upstream remote kept); PLAN/CLAUDE/STATUS/THIRD_PARTY docs
- [x] Step 0: ffmpeg (Gyan full 9.0.2), yt-dlp, uv, Python 3.11, `.venv`, `.[gpu,dev]`. `autoclip doctor` OK, CUDA visible,
      int8_float32. TwitchDownloaderCLI 1.56.5 is NOT in winget: unzipped from the GitHub release to
      `C:\Users\ahmad\tools\TwitchDownloaderCLI`. NVENC unusable with driver 582.78 -> libx264 (fine).
- [x] Step 1 baseline (3 clips, AutoClip unchanged, centre-crop TRACK reframe). No LLM API key exists, so the clips were
      picked by Claude from the transcript instead of AutoClip's built-in provider. Finding: unchanged AutoClip drops the
      streamer entirely (gameplay centre-crop only), which is why FACECAM/REACTION exist.
      Output: `C:\Users\ahmad\.autoclip\exports\514403339be441a3\` (for Ahmad to judge).
- [x] 2a ingest: `stream/ingest.py` (TwitchDownloaderCLI wrapper, chat JSON -> `ChatLog`, trim-aware, disk guard). A 3 h slice
      (2:00:00-5:00:00) + chat stored together (4.2 GB).
- [x] 2b `pipeline/hype.py` (Codex gpt-6.1-sol/medium). Peaks + `stream/hype_eval.py` (viewer-clip ground truth, needs Twitch
      client id/secret from Ahmad; NOT run yet).
- [x] 2c `pipeline/layouts.py`, `facecam.py` + export integration (Codex). Facecam detector re-worked by me after it found
      nothing on real footage (small corner webcam, no border).
- [x] 2d `pipeline/rules.py`, `profanity.py`, `stream/campaigns.py`, hook overlay (Codex); disclosure overlay, logo overlay,
      caption phrases, deadline fields added by me.
- [x] 2e `/clip` skill (`.claude/skills/clip/SKILL.md`), `clip stream`, `stream/pipeline.py`, cut-point QA (`pipeline/cutqa.py`)
- [x] 2f Opus review: 6 blocking issues found and fixed (see git log).
- [ ] Final run + checks 1-3 + `pytest` (see bottom when done)

## Known gaps / for Ahmad
- `campaigns/assets/kreekcraft-logo.png` (official logo from the campaign materials) is missing: real KreekCraft clips are BLOCKED by
  rules until it exists. `kreekcraft-gta6-test.yaml` uses a generated placeholder: pipeline test only, never post those clips.
- Twitch Client ID/secret (env `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET`) needed for the viewer-clip hype check.
- Whisper: transcription of long audio is now chunked (20 min) to avoid MemoryError on 16 GB.
