# Campaign rules

Load a file with `load_campaign("example-gta-streamer")`, an explicit path, or
`load_campaign(name, campaigns_dir=...)`. Named files default to this checkout's
`campaigns/` directory; `CLIPSTUDIO_CAMPAIGNS_DIR` overrides that location, including
for installed packages. YAML uses safe loading and unknown fields are rejected.

The example is a template, not creator permission. Platforms accept `tiktok`,
`youtube`, and `instagram`. Duration bounds are inclusive seconds. Required
hashtags and mentions compare explicit `ClipFacts` lists case-insensitively,
ignoring a leading `#` or `@`. Banned words match whole words; banned topics match
substrings across title, caption, hook, and transcript. Title limits count characters.

`today_only` requires a source timestamp on the same UTC date as `facts.now` (or
the current clock), no future timestamp, and age at most `max_age_hours` (default
24). Naive timestamps mean UTC. There is no separate campaign stream-date field;
pass the campaign's evaluation time as `facts.now` for reproducible checks.

`spoiler_policy: light` permits reactions with a review warning; `strict` blocks
them; `none` ignores reactions. Raw cinematics are always blocked. Captions, a
hook and a reframe are always required. Blocking violations set QA to zero;
otherwise each warning deducts ten points from 100.

`swear_filter` accepts `off`, `mask`, or `bleep`. Both enabled modes mask caption
words while preserving timing. Derive audio intervals from original words before
masking. The plain ffmpeg audio filter mutes intervals rather than generating a
tone; `tone_hz` is reserved. This small English vocabulary is a best-effort filter,
not a complete moderation system. `rate_per_1k_usd` and `notes` are informational.

Hook helpers return an event/style pair. Hooks start at clip time zero, default to
two seconds, fade, wrap to at most two lines, and truncate excess text with `...`.
`center_y_frac` positions captions at a frame-height fraction across all presets.
All code in this task is original; no third-party implementation was ported.
