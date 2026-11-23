# Crash-out evaluation

Acceptance: FAIL. Both retained-voice coverage values remain 0%; uncapped proposals exist but lose ranking under the 15/hour budget. Mixed audio does not establish streamer identity.

Exploratory defaults; no ground-truth tuning. Audio and transcript times are slice-local; tables below use source seconds.
Coverage = best single candidate intersection / annotated moment duration, with a 50% threshold (union also reported). Chat overlap = intersection / shorter window >= 50%.
All selected existing candidates have chat samples (Day 2/3/4: 15/15/14); overlap is against these chat-backed windows, which may also contain loudness or viewer-clip evidence.
Mixed audio and undiarized transcripts cannot establish streamer identity. Nearby words (within 12 s) suppress speech-free stretches; game dialogue can still pass.
New defaults: 120 s speech-conditioned median/MAD z-score; pitch >=20% for 0.5-10 s OR loudness z>=1.5 OR a token-backed speech-rate burst. Bounded joint scoring; 15 candidates per hour. No timestamp-specific rules. Recordings shorter than 240 s retain an at-least-one-candidate exception; the evaluated VODs all obey <=15/hour. Speech-rate counts use 1 s transcript bins over a nominal 4 s neighborhood.

| VOD | Voice candidates (per hour) | Chat-backed overlap fraction | NEW | Coverage | DSP wall time |
|---|---:|---:|---:|---|---:|
| Day 2 2933758895 | 44 (14.67/h) | 9/44 (20.5%) | 35 | jet-ski: NO (best 0.0%, union 0.0%, target 7661-7705) | 22.71 s / 3.00 h |
| Day 3 2934981732 | 34 (14.57/h) | 4/34 (11.8%) | 30 | no annotation | 15.60 s / 2.33 h |
| Day 4 2936183180 | 8 (13.58/h) | 5/8 (62.5%) | 3 | tiger: NO (best 0.0%, union 0.0%, target 928-957) | 5.54 s / 0.59 h |

## Diagnosis and limitations

Jet-ski: nearby words pass throughout. Most hops fail the >=5 dB and >=1.5 robust-z loudness conjunction; at 7674.5 s rise=4.98 dB, z=1.05, F0=1.97x, but pitch lasts only 1 s and fails the old 2 s minimum. At 7701.5-7703.5 s pitch DOES qualify before ranking. Thus the old hourly ranking cap also removes a valid proposal near this annotation. Dedupe is not the cause: coverage is measured on voice candidates before dedupe.
Tiger: nearby words pass. At 929.5 s loudness rises 21.68 dB but z=1.37 misses 1.5; F0=2.03x lasts 1 s. At 932.5 s F0=2.68x is again isolated. The old 2 s pitch minimum and inflated mixed silence/voice baseline scale suppress these short reactions before the cap. Dedupe is not involved.
The first generalized revision (same 20% pitch, speech-conditioned 120 s z baseline, 0.5 s hop) produced Day 2 45 (15.00/h), overlap 11/45, coverage 0%; Day 3 35 (15.00/h), overlap 4/35; Day 4 9 (15.28/h), overlap 7/9, coverage 38.8%. The final revision fixes a general context-merging defect: merge events within 4 s, rather than chaining overlapping context windows into arbitrary 60 s tiles. It also scores normalized onset sharpness and floors partial-hour budgets. No annotation timestamps enter detection or ranking; these changes were not selected by a threshold sweep.

## Earlier inconsistent-input rerun

Recovered session rollout-2026-11-21T23-19-08-01a20031-1a8b-7eb1-91ed-7e1f04b942f3.jsonl, ordinal 266 (22:30:06Z): one Day 2 candidate (source 7200-7227.5, peak 7203.5), DSP 2.16 s; Day 3 and Day 4 reported missing prepared metadata. Ordinal 275 then found the expected files (Day 2/3/4 audio sizes 345599958/268800124/67840968 bytes) and Day 2 stream offset 7200, duration 10800.01. Ordinal 318 subsequently read the same paths, found one Day 3 and one Day 4 job, and decoded Day 2 to 10799 hops / 10799.99 s. The original note is in parent session 23-18-17, ordinal 514.
The bad run did not record decoded duration or input hashes. There is no evidence proving that prepared inputs changed, a slice offset differed, or different files were selected. Root cause remains undetermined; incomplete decoding is a hypothesis, not an established explanation. This report records exact selected files, metadata, sizes, timestamps and SHA256 hashes and rejects decoded-duration mismatches. Paths embedded in stream.json refer to an earlier C: storage location; resolution deliberately uses the existing D: prepared directories.

## Day 2: 2933758895

Audio: `D:\autoclip\work\05a6dc5ea9164c73\audio.wav`; transcript: `D:\autoclip\work\05a6dc5ea9164c73\transcript.json`; existing candidates: `D:\autoclip\work\05a6dc5ea9164c73\candidates.json`.
Source offset: 7200 s. Detector runtime: 7.57 seconds per audio hour.

Input `D:\autoclip\work\05a6dc5ea9164c73\audio.wav`: 345599958 bytes; mtime 1795147698609342600; SHA256 `e4bb3e61dc0ed180b49c783e96911f1729dc5d6e915a16c82ad69dc0c9ce10d9`.
Input `D:\autoclip\work\05a6dc5ea9164c73\transcript.json`: 1322930 bytes; mtime 1795149120128470400; SHA256 `1b0a9833d42dc73c6bfb9657e4f5eb34495271653a93d637dcb7cf9197063ae7`.
Input `D:\autoclip\work\05a6dc5ea9164c73\candidates.json`: 46199 bytes; mtime 1795230885031891400; SHA256 `248369c60b1bbf8be086d5570e97a23c85943b475fc63429cab9d4d8b271f475`.
Input `D:\autoclip\streams\2933758895_7200-18000\stream.json`: 445 bytes; mtime 1795230879002928100; SHA256 `cfeda86329efe46c2adb1f02d27cffb72110d1e3f9b0ae474cd76038b985ceaf`.

Reconstructed first-pass output: 30 candidates; 1 merged proposals touch this annotation before the hourly cap, 0 survive it.

### First-pass raw per-second diagnosis

F0 is ratio to preceding voiced 120 s median; 0 means no F0. Word present means a recognized word starts in that second. The audio speech gate checks level/ratio/occupancy; nearby uses the exact original floor/ceil 12 s histogram gate. Old eligible includes the original score >=2 and precedes ranking/cap and dedupe. All decoded feature arrays were finite.

| Source second | Rise dB | Robust z | F0 ratio | Word present | Audio speech gate | Nearby speech gate | Pitch run s | Old score | Old eligible | New eligible in second |
|---:|---:|---:|---:|---|---|---|---:|---:|---|---|
| 7646.5 | 4.08 | 0.87 | 1.05 | True | True | True | 0 | 2.73 | False | False |
| 7647.5 | 2.19 | 0.47 | 1.05 | True | True | True | 0 | 0.47 | False | True |
| 7648.5 | -0.43 | 0.00 | 0.71 | True | False | True | 0 | 1.50 | False | False |
| 7649.5 | -6.10 | 0.00 | 0.65 | True | False | True | 0 | 1.50 | False | False |
| 7650.5 | 1.83 | 0.39 | 1.41 | True | True | True | 1 | 3.05 | False | True |
| 7651.5 | -0.30 | 0.00 | 0.00 | True | True | True | 0 | 1.50 | False | False |
| 7652.5 | -1.56 | 0.00 | 0.64 | True | True | True | 0 | 1.50 | False | False |
| 7653.5 | 3.60 | 0.83 | 1.46 | True | True | True | 1 | 4.75 | False | True |
| 7654.5 | 4.39 | 1.02 | 1.35 | True | True | True | 0 | 2.58 | False | True |
| 7655.5 | -1.20 | 0.00 | 0.96 | True | False | True | 0 | 1.50 | False | False |
| 7656.5 | -1.69 | 0.00 | 0.73 | True | True | True | 0 | 0.00 | False | False |
| 7657.5 | -2.26 | 0.00 | 1.45 | False | True | True | 1 | 2.00 | False | True |
| 7658.5 | -1.43 | 0.00 | 0.00 | True | False | True | 0 | 1.57 | False | False |
| 7659.5 | 3.16 | 0.79 | 0.63 | True | True | True | 0 | 1.16 | False | False |
| 7660.5 | -17.85 | 0.00 | 0.51 | True | False | True | 0 | 1.50 | False | False |
| 7661.5 | 3.59 | 0.88 | 0.84 | True | True | True | 0 | 3.88 | False | True |
| 7662.5 | 3.03 | 0.74 | 0.90 | True | True | True | 0 | 2.24 | False | True |
| 7663.5 | 1.05 | 0.26 | 0.82 | True | True | True | 0 | 0.26 | False | True |
| 7664.5 | 2.52 | 0.63 | 0.94 | True | True | True | 0 | 0.75 | False | True |
| 7665.5 | -2.09 | 0.00 | 1.45 | True | True | True | 1 | 2.00 | False | True |
| 7666.5 | -11.14 | 0.00 | 0.58 | False | False | True | 0 | 0.00 | False | False |
| 7667.5 | -10.33 | 0.00 | 0.73 | True | False | True | 0 | 1.56 | False | False |
| 7668.5 | -12.58 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 7669.5 | 2.92 | 0.69 | 0.00 | False | True | True | 0 | 1.97 | False | False |
| 7670.5 | -6.30 | 0.00 | 0.00 | False | False | True | 0 | 2.50 | False | False |
| 7671.5 | -4.77 | 0.00 | 0.00 | False | False | True | 0 | 0.11 | False | False |
| 7672.5 | -6.42 | 0.00 | 1.56 | False | False | True | 0 | 2.00 | False | False |
| 7673.5 | -6.05 | 0.00 | 0.00 | False | True | True | 0 | 0.03 | False | False |
| 7674.5 | 4.98 | 1.05 | 1.97 | False | True | True | 1 | 3.96 | False | True |
| 7675.5 | -10.48 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 7676.5 | -3.39 | 0.00 | 1.02 | False | True | True | 0 | 2.08 | False | False |
| 7677.5 | -2.15 | 0.00 | 0.00 | False | False | True | 0 | 0.10 | False | False |
| 7678.5 | -1.91 | 0.00 | 0.38 | False | True | True | 0 | 0.01 | False | False |
| 7679.5 | -3.31 | 0.00 | 0.60 | False | True | True | 0 | 1.50 | False | False |
| 7680.5 | -2.03 | 0.00 | 0.73 | False | False | True | 0 | 1.60 | False | False |
| 7681.5 | -4.14 | 0.00 | 0.00 | False | True | True | 0 | 1.50 | False | False |
| 7682.5 | -0.84 | 0.00 | 0.80 | True | False | True | 0 | 1.76 | False | False |
| 7683.5 | -0.11 | 0.00 | 0.00 | True | True | True | 0 | 1.55 | False | True |
| 7684.5 | -5.78 | 0.00 | 0.62 | True | False | True | 0 | 0.00 | False | False |
| 7685.5 | 2.98 | 0.60 | 0.70 | True | True | True | 0 | 2.83 | False | True |
| 7686.5 | -0.65 | 0.00 | 0.64 | True | True | True | 0 | 1.50 | False | True |
| 7687.5 | -11.61 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | True |
| 7688.5 | 3.38 | 0.69 | 0.68 | True | True | True | 0 | 3.44 | False | False |
| 7689.5 | -1.37 | 0.00 | 0.67 | True | True | True | 0 | 1.50 | False | False |
| 7690.5 | 3.60 | 0.76 | 0.65 | True | True | True | 0 | 1.17 | False | False |
| 7691.5 | 2.65 | 0.56 | 0.64 | True | True | True | 0 | 2.06 | False | False |
| 7692.5 | -7.86 | 0.00 | 0.64 | False | True | True | 0 | 1.50 | False | False |
| 7693.5 | 1.82 | 0.40 | 0.66 | True | True | True | 0 | 1.20 | False | True |
| 7694.5 | 2.45 | 0.53 | 1.27 | True | True | True | 0 | 2.09 | False | True |
| 7695.5 | 5.40 | 1.17 | 1.21 | True | True | True | 0 | 3.92 | False | True |
| 7696.5 | 1.06 | 0.23 | 1.68 | True | True | True | 1 | 3.73 | False | True |
| 7697.5 | 3.13 | 0.68 | 0.90 | True | True | True | 0 | 0.85 | False | True |
| 7698.5 | 1.93 | 0.41 | 0.97 | True | False | True | 0 | 1.91 | False | False |
| 7699.5 | 5.42 | 1.20 | 0.96 | True | True | True | 0 | 2.99 | False | False |
| 7700.5 | 4.28 | 0.95 | 1.04 | False | True | True | 0 | 3.45 | False | True |
| 7701.5 | 4.43 | 0.95 | 2.21 | False | True | True | 3 | 5.47 | True | True |
| 7702.5 | 4.81 | 1.03 | 1.98 | False | True | True | 3 | 3.07 | True | True |
| 7703.5 | 6.81 | 1.45 | 1.96 | False | True | True | 3 | 3.61 | True | True |
| 7704.5 | -1.91 | 0.00 | 1.77 | False | False | True | 0 | 3.50 | False | True |
| 7705.5 | -2.71 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | True |
| 7706.5 | 0.96 | 0.21 | 0.00 | True | False | True | 0 | 3.01 | False | False |
| 7707.5 | 10.31 | 2.23 | 0.55 | True | True | True | 0 | 4.52 | True | True |
| 7708.5 | 7.55 | 1.62 | 1.03 | True | False | True | 0 | 3.12 | False | True |
| 7709.5 | -0.07 | 0.00 | 1.09 | True | True | True | 0 | 1.50 | False | False |
| 7710.5 | -19.20 | 0.00 | 0.00 | False | False | True | 0 | 1.00 | False | False |
| 7711.5 | -1.84 | 0.00 | 0.00 | True | False | True | 0 | 3.95 | False | False |
| 7712.5 | -7.86 | 0.00 | 1.45 | False | False | True | 0 | 4.50 | False | False |
| 7713.5 | 9.38 | 2.01 | 2.07 | True | False | True | 0 | 6.94 | False | True |
| 7714.5 | 7.79 | 1.64 | 1.12 | True | False | True | 0 | 2.64 | False | True |
| 7715.5 | -21.94 | 0.00 | 0.00 | True | True | True | 0 | 1.00 | False | False |
| 7716.5 | 11.98 | 2.51 | 0.56 | True | False | True | 0 | 5.51 | False | True |
| 7717.5 | 13.70 | 2.90 | 1.40 | True | True | True | 0 | 4.55 | True | True |
| 7718.5 | 10.41 | 2.20 | 1.00 | True | True | True | 0 | 3.70 | True | True |
| 7719.5 | 14.46 | 3.00 | 0.60 | True | True | True | 0 | 4.84 | True | True |

Uncapped proposals touching the annotation: 7625.75-7675.25 (score 5.25); 7662.25-7684.25 (score 5.34); 7671.75-7697.75 (score 3.95); 7682.75-7718.75 (score 5.42); 7701.25-7759.75 (score 5.67). These are diagnostic only; reported coverage uses capped output.

### New ranked candidates

| Rank | Source window | Source peak | Score | NEW | Signals |
|---:|---|---:|---:|---|---|
| 1 | 7854.2-7913.2 | 7882.2 | 6.25 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 2 | 11268.8-11304.8 | 11287.8 | 6.25 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 3 | 12194.8-12219.8 | 12209.8 | 6.25 | yes | laugh_burst, pitch_jump, rage_burst, voice_jump |
| 4 | 12569.2-12601.2 | 12583.8 | 6.25 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, scream_like, voice_jump |
| 5 | 13125.8-13168.8 | 13140.8 | 6.25 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 6 | 16385.8-16422.2 | 16397.8 | 6.25 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 7 | 17078.2-17138.2 | 17099.2 | 6.25 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 8 | 17238.8-17297.2 | 17271.8 | 6.25 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 9 | 17687.2-17715.2 | 17702.2 | 6.25 | no | laugh_burst, pitch_jump, rage_burst, voice_jump |
| 10 | 17476.8-17504.8 | 17489.8 | 6.22 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 11 | 11178.2-11216.2 | 11196.2 | 6.21 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 12 | 14174.2-14215.2 | 14198.8 | 6.19 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 13 | 9995.8-10047.2 | 10031.8 | 6.18 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 14 | 14865.8-14889.8 | 14878.8 | 6.17 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 15 | 13539.8-13575.8 | 13551.8 | 6.12 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 16 | 15132.2-15159.8 | 15144.2 | 6.12 | yes | laugh_burst, pitch_jump, rage_burst, voice_jump |
| 17 | 13583.2-13609.8 | 13595.2 | 6.11 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 18 | 15629.8-15656.2 | 15643.2 | 6.11 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 19 | 12929.8-12958.8 | 12943.2 | 6.1 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, scream_like, voice_jump |
| 20 | 16712.8-16740.2 | 16728.8 | 6.08 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 21 | 8435.2-8482.8 | 8454.8 | 6.07 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 22 | 13779.8-13816.2 | 13803.8 | 6.07 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 23 | 10177.8-10222.2 | 10206.2 | 6.06 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 24 | 16650.8-16685.8 | 16666.8 | 6.01 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 25 | 12417.2-12454.2 | 12444.2 | 5.98 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 26 | 11321.8-11377.2 | 11341.2 | 5.97 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, scream_like, voice_jump |
| 27 | 12707.2-12731.2 | 12720.2 | 5.97 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 28 | 8954.2-8993.8 | 8967.2 | 5.95 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 29 | 13315.8-13354.2 | 13341.2 | 5.92 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 30 | 14159.8-14182.8 | 14171.8 | 5.92 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 31 | 9904.8-9933.8 | 9920.2 | 5.9 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 32 | 17049.8-17091.2 | 17068.8 | 5.9 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, scream_like, voice_jump |
| 33 | 15691.2-15730.8 | 15712.8 | 5.89 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, scream_like, voice_jump |
| 34 | 16204.2-16233.8 | 16220.8 | 5.88 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 35 | 7326.2-7367.8 | 7351.8 | 5.87 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 36 | 10364.2-10395.8 | 10376.2 | 5.87 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 37 | 10206.8-10249.2 | 10222.8 | 5.85 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 38 | 10297.2-10340.2 | 10310.8 | 5.84 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 39 | 7739.8-7769.2 | 7753.2 | 5.8 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 40 | 9413.8-9458.2 | 9439.8 | 5.8 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 41 | 14539.8-14569.2 | 14555.2 | 5.8 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 42 | 7997.2-8034.2 | 8009.2 | 5.79 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 43 | 7443.8-7474.8 | 7463.8 | 5.75 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 44 | 7900.8-7934.2 | 7914.8 | 5.75 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |

## Day 3: 2934981732

Audio: `D:\autoclip\work\11f5c9fb80be4f45\audio.wav`; transcript: `D:\autoclip\work\11f5c9fb80be4f45\transcript.json`; existing candidates: `D:\autoclip\work\11f5c9fb80be4f45\candidates.json`.
Source offset: 6000 s. Detector runtime: 6.69 seconds per audio hour.

Input `D:\autoclip\work\11f5c9fb80be4f45\audio.wav`: 268800124 bytes; mtime 1795229000697551900; SHA256 `0bc87cdde85e949df80e44ebba994be5bc624c5d5006c5c341912473da630ffa`.
Input `D:\autoclip\work\11f5c9fb80be4f45\transcript.json`: 1182654 bytes; mtime 1795231599969183400; SHA256 `461a1fc9fb13eba1aec5d1b733ee19e0f5622f1c66c9c836958c63e72753400d`.
Input `D:\autoclip\work\11f5c9fb80be4f45\candidates.json`: 44408 bytes; mtime 1795231907024661700; SHA256 `e6c6c727bff95b9b789bd1a44878c49f289fe2b1a352db2e16936c374e586350`.
Input `D:\autoclip\streams\2934981732_6000-14400\stream.json`: 471 bytes; mtime 1795231902470929100; SHA256 `a83c19c3586c9ca6a9a7db84833a3002c79b82a1b08189939c198225a8dd6d3e`.

| Rank | Source window | Source peak | Score | NEW | Signals |
|---:|---|---:|---:|---|---|
| 1 | 9725.2-9759.2 | 9737.2 | 6.25 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 2 | 10693.8-10715.8 | 10705.8 | 6.25 | yes | voice_jump, bright_shout, pitch_jump, scream_like, rage_burst, laugh_burst |
| 3 | 11640.2-11699.8 | 11672.2 | 6.25 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 4 | 14185.2-14213.8 | 14201.2 | 6.25 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 5 | 11813.2-11851.8 | 11828.2 | 6.2 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 6 | 8978.2-9020.2 | 9010.2 | 6.18 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 7 | 13065.2-13116.2 | 13092.8 | 6.18 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 8 | 8553.8-8581.2 | 8567.2 | 6.17 | yes | laugh_burst, pitch_jump, rage_burst, voice_jump |
| 9 | 10187.2-10215.8 | 10205.8 | 6.15 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 10 | 14133.2-14170.8 | 14156.2 | 6.15 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 11 | 11050.2-11076.2 | 11063.8 | 6.13 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 12 | 7717.8-7742.8 | 7730.8 | 6.12 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 13 | 11774.2-11833.8 | 11823.8 | 6.12 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 14 | 13661.8-13721.8 | 13696.2 | 6.1 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 15 | 9799.2-9824.2 | 9814.2 | 6.04 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 16 | 9498.8-9530.2 | 9514.2 | 6.02 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, scream_like, voice_jump |
| 17 | 8821.2-8847.8 | 8833.2 | 6.01 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 18 | 8688.2-8723.2 | 8710.8 | 6.0 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 19 | 10141.2-10168.8 | 10155.8 | 6.0 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 20 | 11834.8-11879.8 | 11857.8 | 6.0 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 21 | 6125.8-6180.8 | 6156.2 | 5.99 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 22 | 7261.2-7321.2 | 7288.2 | 5.99 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 23 | 8370.2-8408.8 | 8389.8 | 5.97 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 24 | 11148.2-11208.2 | 11177.2 | 5.97 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 25 | 6080.2-6112.2 | 6093.2 | 5.96 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 26 | 11560.2-11619.2 | 11605.8 | 5.95 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 27 | 13508.2-13551.8 | 13535.2 | 5.94 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 28 | 11526.2-11569.2 | 11538.2 | 5.93 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 29 | 9295.2-9331.8 | 9316.8 | 5.92 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 30 | 9838.2-9878.2 | 9854.8 | 5.92 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 31 | 7300.8-7331.8 | 7316.2 | 5.9 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 32 | 6427.2-6452.2 | 6439.2 | 5.87 | yes | laugh_burst, pitch_jump, rage_burst, voice_jump |
| 33 | 8294.8-8320.2 | 8308.2 | 5.86 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 34 | 9533.2-9569.8 | 9551.2 | 5.85 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, scream_like, voice_jump |

## Day 4: 2936183180

Audio: `D:\autoclip\work\32b5cf7d87d04758\audio.wav`; transcript: `D:\autoclip\work\32b5cf7d87d04758\transcript.json`; existing candidates: `D:\autoclip\work\32b5cf7d87d04758\candidates.json`.
Source offset: 0 s. Detector runtime: 9.40 seconds per audio hour.

Input `D:\autoclip\work\32b5cf7d87d04758\audio.wav`: 67840968 bytes; mtime 1795275748652815600; SHA256 `2f37a4fc1cbbe222a57870342d4cc401d765c6ae38f04a4131f0f514b2f7a2a4`.
Input `D:\autoclip\work\32b5cf7d87d04758\transcript.json`: 339880 bytes; mtime 1795276193953748000; SHA256 `4f0268c66bf2c420e4434921e77656d5b0f3cc7671f7b6b01b9ea7ac8f57177e`.
Input `D:\autoclip\work\32b5cf7d87d04758\candidates.json`: 53087 bytes; mtime 1795300898588426300; SHA256 `744869831ccc2555aae406ac2bc57945dd3f80a578a207751f3e47e535b22266`.
Input `D:\autoclip\streams\2936183180\stream.json`: 384 bytes; mtime 1795300893788144200; SHA256 `bf06883886028e9b05adb7d12c720a4458c722b55cdb09d1d55dbdb7494a3372`.

Reconstructed first-pass output: 6 candidates; 0 merged proposals touch this annotation before the hourly cap, 0 survive it.

### First-pass raw per-second diagnosis

F0 is ratio to preceding voiced 120 s median; 0 means no F0. Word present means a recognized word starts in that second. The audio speech gate checks level/ratio/occupancy; nearby uses the exact original floor/ceil 12 s histogram gate. Old eligible includes the original score >=2 and precedes ranking/cap and dedupe. All decoded feature arrays were finite.

| Source second | Rise dB | Robust z | F0 ratio | Word present | Audio speech gate | Nearby speech gate | Pitch run s | Old score | Old eligible | New eligible in second |
|---:|---:|---:|---:|---|---|---|---:|---:|---|---|
| 913.5 | -8.70 | 0.00 | 0.00 | True | False | True | 0 | 1.50 | False | False |
| 914.5 | 11.07 | 0.77 | 0.00 | True | True | True | 0 | 3.77 | False | False |
| 915.5 | -6.73 | 0.00 | 1.28 | True | False | True | 0 | 0.00 | False | False |
| 916.5 | -7.83 | 0.00 | 1.18 | False | False | True | 0 | 1.50 | False | False |
| 917.5 | -11.55 | 0.00 | 0.00 | False | False | True | 0 | 1.50 | False | False |
| 918.5 | -9.13 | 0.00 | 0.79 | False | False | True | 0 | 0.17 | False | False |
| 919.5 | 9.95 | 0.63 | 0.72 | True | True | True | 0 | 3.13 | False | False |
| 920.5 | 10.53 | 0.66 | 0.64 | True | False | True | 0 | 2.21 | False | False |
| 921.5 | 17.36 | 1.10 | 1.42 | True | True | True | 1 | 4.68 | False | True |
| 922.5 | 16.30 | 0.99 | 1.12 | True | True | True | 0 | 1.99 | False | True |
| 923.5 | 15.98 | 0.96 | 1.04 | True | True | True | 0 | 3.46 | False | True |
| 924.5 | 9.29 | 0.56 | 0.93 | True | False | True | 0 | 0.56 | False | False |
| 925.5 | -6.99 | 0.00 | 1.08 | False | False | True | 0 | 0.00 | False | False |
| 926.5 | -3.57 | 0.00 | 0.81 | False | False | True | 0 | 0.29 | False | False |
| 927.5 | -2.95 | 0.00 | 0.95 | False | False | True | 0 | 1.55 | False | False |
| 928.5 | 4.57 | 0.28 | 1.25 | True | False | True | 0 | 0.87 | False | False |
| 929.5 | 21.68 | 1.37 | 2.03 | False | True | True | 1 | 7.30 | False | True |
| 930.5 | 12.79 | 0.81 | 0.00 | False | False | True | 0 | 1.81 | False | True |
| 931.5 | 18.16 | 1.17 | 0.64 | False | True | True | 0 | 2.65 | False | True |
| 932.5 | 17.02 | 1.10 | 2.68 | False | True | True | 1 | 4.10 | False | True |
| 933.5 | -1.75 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 934.5 | -8.32 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 935.5 | -3.91 | 0.00 | 0.00 | False | False | True | 0 | 1.84 | False | False |
| 936.5 | -1.58 | 0.00 | 0.00 | False | False | True | 0 | 0.19 | False | False |
| 937.5 | -6.82 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 938.5 | -15.92 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 939.5 | -23.52 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 940.5 | -31.56 | 0.00 | 0.00 | False | False | True | 0 | 1.50 | False | False |
| 941.5 | -50.08 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 942.5 | -70.39 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 943.5 | -71.69 | 0.00 | 0.00 | False | False | True | 0 | 0.00 | False | False |
| 944.5 | -70.61 | 0.00 | 0.00 | False | False | True | 0 | 0.07 | False | False |
| 945.5 | -42.98 | 0.00 | 0.00 | False | False | True | 0 | 3.00 | False | False |
| 946.5 | -0.31 | 0.00 | 0.00 | True | False | True | 0 | 2.50 | False | False |
| 947.5 | -3.90 | 0.00 | 0.00 | True | False | True | 0 | 0.00 | False | False |
| 948.5 | -3.24 | 0.00 | 0.00 | True | False | True | 0 | 0.03 | False | False |
| 949.5 | 19.06 | 1.06 | 1.50 | True | True | True | 1 | 5.56 | False | True |
| 950.5 | 21.66 | 1.21 | 1.16 | True | True | True | 0 | 2.43 | False | True |
| 951.5 | 19.24 | 1.07 | 1.18 | True | True | True | 0 | 3.57 | False | False |
| 952.5 | 14.11 | 0.77 | 1.34 | True | False | True | 0 | 1.77 | False | True |
| 953.5 | -3.03 | 0.00 | 1.14 | False | True | True | 0 | 2.50 | False | True |
| 954.5 | -4.05 | 0.00 | 1.13 | True | True | True | 0 | 0.00 | False | True |
| 955.5 | -4.63 | 0.00 | 1.18 | True | True | True | 0 | 1.50 | False | True |
| 956.5 | 1.26 | 0.07 | 1.42 | True | True | True | 1 | 3.56 | False | True |
| 957.5 | 14.84 | 0.86 | 0.00 | True | True | True | 0 | 2.99 | False | False |
| 958.5 | 17.37 | 1.00 | 1.05 | True | True | True | 0 | 3.71 | False | True |
| 959.5 | 15.01 | 0.84 | 2.48 | True | True | True | 1 | 5.34 | False | True |
| 960.5 | -19.66 | 0.00 | 0.00 | True | False | True | 0 | 1.00 | False | False |
| 961.5 | 18.59 | 1.03 | 1.06 | True | True | True | 0 | 3.53 | False | False |
| 962.5 | 16.04 | 0.89 | 1.02 | True | True | True | 0 | 1.89 | False | False |
| 963.5 | 1.11 | 0.06 | 0.00 | True | False | True | 0 | 2.56 | False | False |
| 964.5 | 17.06 | 0.93 | 1.05 | True | True | True | 0 | 3.30 | False | False |
| 965.5 | 0.66 | 0.04 | 1.08 | False | False | True | 0 | 2.54 | False | False |
| 966.5 | 12.18 | 0.68 | 1.01 | True | True | True | 0 | 2.66 | False | False |
| 967.5 | -0.79 | 0.00 | 0.90 | True | False | True | 0 | 1.00 | False | False |
| 968.5 | 7.76 | 0.43 | 0.65 | True | True | True | 0 | 2.15 | False | False |
| 969.5 | -21.35 | 0.00 | 0.98 | False | False | True | 0 | 2.50 | False | False |
| 970.5 | 6.13 | 0.34 | 0.78 | True | False | True | 0 | 1.84 | False | False |
| 971.5 | -21.11 | 0.00 | 1.20 | False | False | True | 0 | 1.00 | False | False |

Uncapped proposals touching the annotation: 909.75-933.75 (score 5.53); 917.25-942.25 (score 5.72); 937.75-969.25 (score 5.45). These are diagnostic only; reported coverage uses capped output.

### New ranked candidates

| Rank | Source window | Source peak | Score | NEW | Signals |
|---:|---|---:|---:|---|---|
| 1 | 1424.8-1450.2 | 1439.2 | 6.05 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 2 | 1454.2-1489.2 | 1469.2 | 5.99 | no | laugh_burst, pitch_jump, rage_burst, voice_jump |
| 3 | 1574.8-1611.2 | 1586.8 | 5.99 | yes | laugh_burst, pitch_jump, rage_burst, voice_jump |
| 4 | 284.8-325.8 | 296.8 | 5.91 | yes | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 5 | 963.2-994.8 | 977.2 | 5.78 | no | bright_shout, laugh_burst, pitch_jump, rage_burst, voice_jump |
| 6 | 124.2-150.8 | 138.8 | 5.75 | no | bright_shout, laugh_burst, rage_burst, voice_jump |
| 7 | 370.8-395.2 | 385.2 | 5.75 | no | laugh_burst, pitch_jump, voice_jump |
| 8 | 713.8-743.2 | 726.8 | 5.75 | yes | bright_shout, laugh_burst, pitch_jump, voice_jump |

## Verification

All commands ran from `C:/Users/ahmad/Desktop/VS_CODE/clip-studio/.claude/worktrees/crashout-detector` with `PYTHONPATH` set to that worktree's `backend` and `C:/Users/ahmad/Desktop/VS_CODE/clip-studio/.venv/Scripts/python.exe` explicitly selected.

- Import verification: `python.exe -c "import autoclip.pipeline.crashout as c; print(c.__file__)"` printed the worktree's `backend/autoclip/pipeline/crashout.py`.
- Detector: `python.exe -m pytest -q tests/test_crashout.py`: 33 passed, 0 skipped, 0 failed (19.16 s). Includes 0.5/1/2 s loudness and pitch bursts, independent token-backed speech-rate burst, steady and varying loud-but-normal baselines, full-hour and fractional-hour caps, and context merging.
- Full suite: `python.exe -m pytest -q`: 840 passed, 24 skipped, 1 failed (301.26 s). Failure: `tests/auto/test_end_to_end_mock.py::test_vod_to_post_to_tracker_with_pause` at line 160: expected three mock uploads, observed one and two still queued. This is outside the allowed detector/eval paths and was not changed. An earlier full run repeated the same failure (836 passed, 24 skipped, 1 failed before the final four test cases were added).
- `python.exe -m ruff check backend/autoclip/pipeline/crashout.py scripts/crashout_eval.py tests/test_crashout.py`: all checks passed. No dependencies installed.
- `python.exe scripts/crashout_eval.py`: completed on prepared read-only Day 2/3/4 inputs; results and hashes above. Final repeated evaluations produced the same candidate counts, overlaps and coverage; wall times varied.

Acceptance remains failed: capped outputs cover 0% of both known moments. Before the budget, best single-window coverage is 59.1% for jet-ski and 66.4% for tiger, but those proposals rank below retained mixed-audio events. This detector cannot verify streamer identity from the supplied mixed audio and undiarized transcript. Further ranking work requires independent labeled streamer reactions/background examples rather than selecting thresholds against these two moments.
