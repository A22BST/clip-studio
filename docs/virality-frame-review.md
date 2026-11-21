# Day 2 clip quality review

Reviewed 2026-11-21. Scope: the eight `*_9x16.mp4` files in `C:\Users\ahmad\.autoclip\exports\05a6dc5ea9164c73`. No code or media was changed. The optional earlier export batch was not needed.

## Evidence and limits

- Used ffprobe JSON (`-show_format -show_streams`) for every file and decoded every complete audio stream with ffmpeg `-af ebur128=peak=true -f null -`.
- Extracted and actually viewed frames at **0, 0.5, 1, 2, duration/2, duration-2 and duration-1 seconds for all eight clips**. Also viewed one-second overview sheets across every clip. These establish visual sequences, not frame-accurate event boundaries. Overview timestamps below are approximate sampling centers.
- Temporary frames, contact sheets, extraction scripts, ffprobe results and EBU R128 logs are outside the repository at `C:\Users\ahmad\AppData\Local\Temp\clipframes-review`, numbered 1-8 in the order of the tables below. Each numbered folder has `required.jpg`, `overview.jpg`, original required-frame JPEGs and `ebur128.txt`; combined probe data is `metadata.json`.
- Additional viewed samples for clips 7 and 8: 0.05, 0.1, 0.25, 1.5, 1.75, 1.9, 2.5, 2.9, 3 and 3.1 seconds, plus duration-0.05. Their `hook-end.jpg` sheets show hook fading and terminal frames.
- **Source availability changed during review:** after the complete first extraction/measurement pass, files 1-6 were no longer present at their supplied paths. A follow-up extraction failed, and a directory check then showed only files 7 and 8. No source files were moved or deleted by this review. Findings for files 1-6 use the preserved first-pass evidence; exact hook fade boundaries and their final decoded frames were not additionally verified.
- The initially read `report.json` and `report.md` describe **only clip 1**, source 7661.09-7705.29 s, facecam layout, QA score 100 and no recorded violations. They provide no event timings or entries for the other seven files. The displayed QA 100 does not resolve the visual issues below.
- Pixel coordinates are approximate visual measurements against 1080x1920 frames, generally rounded to 10 px. Face measurements are bounding-box estimates, not face-detector output. Brightness measurements are Pillow grayscale statistics on the extracted JPEG gameplay region; they are not calibrated video luma or display brightness.
- App UI assessment uses the **user-supplied approximation**, not a live platform overlay: top y=0-250, bottom y=1536-1920, right x=918-1080. An overlap is a risk under that mask, not proof that every app covers that exact location.
- Payoff times are **editorial hypotheses**, supported by viewed action, visible word captions and measured loudness. No listening-based speech, distortion or intelligibility assessment was performed. Loudest moment does not automatically mean narrative payoff. Retention effects are hypotheses; no audience analytics were supplied.

## Overall visual assessment

All eight start on decoded, active content; none of the viewed t=0 frames is black, a loading screen or a dead export frame. However, **all eight lack visible hook text at exactly t=0**, and every hook's first line occupies the top UI risk band. Caption placement and retained stream overlays are more consistent problems than resolution or clipping.

Seven clips use an upper streamer panel of approximately 730 px and lower gameplay panel of 1190 px: **38% streamer / 62% gameplay by panel area**. The streamer panel includes the source background, microphone, attribution and subscriber counter; it is not all face. The door clip instead gives roughly **65% to streamer / 35% to gameplay**, including its separator. These are screen-area ratios, not source-camera crop ratios.

| # | Exact clip filename | t=0 visual interest | Hook / app UI | Word captions | Facecam / split | Main editorial concern |
|---|---|---|---|---|---|---|
| 1 | `a-dog-on-a-jet-ski-actually-came_9x16.mp4` | Bright swimming scene; dog absent | One line, ~72% width; top overlap; right edge slightly beyond x=918 | Large, high contrast, straddles seam | Full face; counter visible; 38/62 | Dog becomes clearly readable only ~27-33 s into 44.2 s |
| 2 | `chat-said-type-1-and-we-robbed-the-store_9x16.mp4` | Character at shop; dim and relatively static | Two lines, ~57% width; first line top overlap, second over face | Seam-level; counter and subtitle compete | Full face; counter visible; 38/62 | Chat/engagement lead-in, then equipment menu, before robbery ~29-32 s |
| 3 | `he-did-not-expect-who-opened-that-door_9x16.mp4` | Door already opening, expressive face | One line, ~82% width; top and right overlap | Below red separator; long line reaches right risk band | Oversized main facecam plus duplicate inset; 65/35 | Reveal starts immediately, then lower panel is blurred ~2.5-10.5 s |
| 4 | `that-was-a-peak-mission_9x16.mp4` | Moving van, ordinary driving image | One line, ~82% width; top and right overlap | Seam-level; some collision with counter/HUD | Full face; counter visible; 38/62 | Escape aftermath and praise, rather than the mission's peak action |
| 5 | `the-snake-survived-and-has-babies_9x16.mp4` | Active scene but gameplay nearly unreadable | One line, ~80% width; top and right overlap | Readable white/yellow on dark scene, at seam | Full face; counter visible; 38/62 | Very dark lead-in; snake not clearly featured until ~8-10 s |
| 6 | `they-deployed-jets-after-me_9x16.mp4` | Aircraft already flying; clear action premise | One line, ~73% width; top overlap, right edge marginal | Seam/HUD competition; long sampled caption remains mostly central | Full face; counter visible; 38/62 | Strong reaction ~21-24 s, after a long flight lead-in |
| 7 | `this-is-the-best-game-of-all-time_9x16.mp4` | Gunfire and visible muzzle flash by 0.5 s | One line, ~80% width; top and right overlap | Sparse streamer captions; tiny game dialogue at bottom | Full face; counter visible; 38/62 | Generic hook; title phrase arrives ~33-38 s after action |
| 8 | `why-is-there-a-bed-in-the-pool_9x16.mp4` | Unusual mattress/pool visible immediately | Two lines, ~80% width; top/right overlap and face obstruction | Seam-level; game dialogue inside bottom mask | Full face; counter visible; 38/62 | Roach reaction appears only ~25-28 s into 29 s |

### Shared text geometry and readability

The single-line hooks have visible letter height around **90-105 px** (~5% frame height), generally at **y=80-190**. Size and thick black outlines make them legible against both sky and dark interiors, but their entire first line lies above the supplied y=250 safe boundary. The two-line hooks extend to approximately **y=350**; only their second line escapes that top band. Their extra line overlays the face rather than using free gameplay space. Hook contrast is good once fully visible; the confirmed early fade in clips 7/8 temporarily reduces it.

For files 1-6, hooks are visible at 0.5 and 1 s and in the approximately 1.5 s overview sample, but absent at the exact 2 s sample: supported duration is **roughly the first two seconds, with disappearance between about 1.5 and 2 s**. Their onset is only bounded between 0 and 0.5 s. For files 7/8, the hook is faint at 0.05 s, stronger at 0.1 s, clear at 0.25-1.75 s, fading at 1.9 s and absent at 2 s. Thus useful full-contrast exposure is appreciably shorter than two seconds. Do not infer identical fade timings for the six unavailable files.

Word captions use condensed white capitals, a yellow active word and a substantial black outline. Typical visible letter heights are **60-80 px** (~3-4% frame height), sufficient in the full-size stills, with variable phrase width. In the standard split they occupy approximately **y=700-780**, crossing the seam at y~730. They sit safely above the bottom UI mask and well below the top mask, but share space with the counter's lower edge and the gameplay compass/status bars. They generally do not cross the eyes or mouth. Door captions sit around **y=1220-1300**, below the red source bar and near the top of the smaller gameplay panel. Separate, much smaller in-game subtitles commonly sit around y=1780-1850 and are inside the supplied bottom UI mask.

## Technical measurements

Every file: **1080x1920, H.264, reported average 60/1 fps; AAC stereo, 48 kHz**. The bitrate figures are ffprobe stream/format averages, not maximum instantaneous rates. EBU true peak is reported here in dBTP; ffmpeg's summary labels the numerical field dBFS under “True peak.”

| # / file stem | Duration s | Video Mb/s | Total Mb/s | Audio kb/s | Integrated LUFS | LRA LU | True peak dBTP |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 `a-dog-on-a-jet-ski-actually-came` | 44.20 | 11.397 | 11.603 | 193.2 | -13.6 | 14.4 | -1.4 |
| 2 `chat-said-type-1-and-we-robbed-the-store` | 37.50 | 6.694 | 6.889 | 194.5 | -14.7 | 11.0 | -1.4 |
| 3 `he-did-not-expect-who-opened-that-door` | 25.60 | 5.332 | 5.537 | 195.6 | -15.3 | 14.6 | -2.2 |
| 4 `that-was-a-peak-mission` | 27.00 | 12.538 | 12.741 | 189.6 | -14.9 | 4.8 | -1.4 |
| 5 `the-snake-survived-and-has-babies` | 29.40 | 6.152 | 6.360 | 194.1 | -14.0 | 9.2 | -1.4 |
| 6 `they-deployed-jets-after-me` | 41.90 | 7.535 | 7.742 | 194.2 | -15.0 | 7.3 | -1.4 |
| 7 `this-is-the-best-game-of-all-time` | 38.20 | 10.936 | 11.133 | 193.3 | -15.1 | 3.8 | -1.4 |
| 8 `why-is-there-a-bed-in-the-pool` | 29.00 | 9.318 | 9.517 | 191.0 | -13.3 | 12.2 | -1.4 |

The encoded dimensions are appropriate for portrait delivery, but do not establish native source detail. Full-size dog and door frames show visibly soft enlarged camera detail; bitrate alone will not restore it. No gross block corruption was seen in the sampled sheets. The high-motion van file uses ~2.35 times the video bitrate of the door file; this is variation, not evidence of a codec fault. No measured true peak reaches 0 dBTP. Loudness differs by only 2 LU across the batch, but dog, door and pool have substantially wider measured dynamics than mission or gunfight. Whether quiet passages are intelligible on a phone still needs listening.

## Payoff timing

“M peak” is the largest measured EBU momentary loudness value, with its log timestamp; it represents an approximately 400 ms loudness window, not a sample peak. Percentages use the full encoded duration. Event windows are deliberately approximate.

| # | Hypothesized payoff from viewed sequence | Position within clip | Loudest M window | Timing implication |
|---|---|---|---|---|
| 1 | Streamer surprise ~12-19 s; dog/jet ski clearly approaching and close ~27-33 s | Reaction 27-43%; clear visual 61-75% | 17.9 s, -7.9 LUFS | Reaction precedes legible dog reveal; long swimming lead-in |
| 2 | Weapon raised / robbery captions ~29-32 s; cash/smashing ~35-37 s | 77-85%; final action 93-99% | 30.7 s, -8.1 LUFS | Actual robbery comes near the end |
| 3 | Door opening / initial surprise ~0-3 s; renewed expressive reaction ~7-8 s | 0-12%; renewed reaction 27-31% | 0.8 s, -10.3 LUFS | Immediate payoff; most runtime is extended response/dialogue |
| 4 | Escape confirmation ~2-5 s; “peak mission” praise ~15-19 s | 7-19%; praise 56-70% | 15.9 s, -8.5 LUFS | Title refers to reaction after a mission rather than a displayed climax |
| 5 | Snake close-up ~8-10 s; “got babies” captions ~15-19 s | 27-34%; babies claim 51-65% | 8.3 s, -7.2 LUFS | First loud reveal and later verbal claim are separate beats |
| 6 | Banking plane / open-mouth reaction ~21-24 s; continued reaction ~25-34 s | Main beat 50-57% | 23.6 s, -8.0 LUFS | Clear emotional peak around midpoint |
| 7 | Gunfight already underway ~0-1 s, sustained through ~24 s; strongest sampled smiling reaction ~25 s; title phrase ~33-38 s | Immediate action; reaction ~65%; phrase 86-99% | 25.1 s, -10.9 LUFS | Good action start; title phrase is a late coda, not a distinct visual reveal |
| 8 | Mattress visible at 0 s; “bed in the pool” captions ~9-11 s; “roaches” reaction ~25-28 s | Immediate object; spoken premise 31-38%; final reaction 86-97% | 27.8 s, -7.5 LUFS | Stronger secondary joke arrives almost at the cut |

## Per-clip findings

### 1. `a-dog-on-a-jet-ski-actually-came_9x16.mp4`

- **Opening/hook:** t=0 is bright, recognizable swimming, but contains neither the dog nor visible hook. “A DOG on a jet ski?!” occupies approximately x=150-930, y=80-190: ~72% frame width, strong white/black contrast, entirely inside the top mask and slightly into the right mask. It is gone by 2 s. The premise is stronger than the actual first image.
- **Captions:** at 0.5 s, “AND PICKS ME UP” spans roughly x=300-780 and y=700-780, crossing the panel join and nearby compass. At 2 s, “I'M GETTING MY CHEEKS” is also on that join. These samples avoid the main face and bottom UI; the seam/counter competition remains visible.
- **Camera/layout:** 38/62 split. Main face is intact, approximately 250-300 px wide, or 23-28% of frame width. Large microphone, `@KreekCraft` attribution and `652,420`/`652,419` counter remain. A broad area of water fills the camera panel to the streamer's right; the panel allocation overstates how much screen is actually reaction.
- **Pacing/ending:** midpoint 22.1 s still shows a relatively distant jet ski. The dog is much clearer ~27-33 s; 42.2/43.2 s show the mounted ride with recap captions. A tighter approach-to-recognition sequence is an editorial hypothesis worth testing. Current length is 44.2 s, the batch maximum.
- **Technical:** 11.397 Mb/s video, -13.6 LUFS, 14.4 LU LRA, -1.4 dBTP. Strong dynamic variation is measured; audible pumping or distortion was not assessed. The report's 44.20 s source interval matches encoded duration.

### 2. `chat-said-type-1-and-we-robbed-the-store_9x16.mp4`

- **Opening/hook:** t=0 shows the player at a shop counter, not a black frame, but gameplay grayscale mean is only 40.7/255, with 54.9% of pixels below 32. “Type 1 if you're / ready” is roughly x=230-850, y=80-350 (~57% width); the first line is in the top mask and “ready” overlays the face. Contrast is strong. Hook disappears by 2 s; `#ad Paid partnership` is still visible at 2 s and absent in the ~3.5 s overview.
- **Captions:** “CHAT” at 0.5 s sits on the standard seam, close to the counter. Later captions show “READY TYPE 1 EVERYBODY,” platform/subscribe prompts and “HANDS UP THIS IS.” Longer overview phrases leave less right-side margin; exact glyph clipping was not established from those thumbnails. Short required-frame captions remain central and clear.
- **Camera/layout:** 38/62, intact face roughly one quarter of frame width, large mic and subscriber count `651,971`. The face is not cut off, but the two-line hook and disclosure compete for facial space.
- **Pacing/ending:** ~4-17 s captions solicit chat/likes/subscriptions/follows; ~17.5-24.5 s gameplay is an equipment wheel rather than robbery action. Gun-up action begins ~29 s, with the largest M window at 30.7 s. At 35.5/36.5 s the player is finally at the display case; the late captions are “GIVE ME THAT CASH” and “SMASH IT.” Most of 37.5 s precedes the promised event.
- **Technical:** 6.694 Mb/s video, -14.7 LUFS, 11.0 LU LRA, -1.4 dBTP. Dimness and long menu dwell are directly visible problems; low bitrate is not established as their cause.

### 3. `he-did-not-expect-who-opened-that-door_9x16.mp4`

- **Opening/hook:** the door is already opening at t=0. “Do NOT open that door” is approximately x=95-985, y=80-190 (~82% width), overlapping both top and right masks. Good outline contrast; absent by 2 s. The warning follows an opening already in progress, so suspense setup is very short.
- **Captions:** around y=1220-1300, below the retained red bar, with 60-80 px letter height. At 12.8 s, “IT BENEDICT HALIFAX REMEMBER” stretches almost across the entire width, into x>918. The native game “Hello?” around y=1850 at 0.5 s is inside bottom UI coverage. Added captions are above bottom UI and below the large face, but consume the small gameplay panel's upper edge.
- **Camera/layout:** main face ~350-420 px wide (32-39% of width), fully framed, with counter `652,553` and red source bar. Upper panel/separator occupies ~1248 px, leaving only ~672 px (35%) for gameplay. A **second, small source facecam and follower overlay remain at gameplay left**, visibly clipped by that crop. This is the clearest duplicate-overlay defect in the batch.
- **Pacing/ending:** reaction starts in the first second, consistent with M peak 0.8 s. The lower panel is visibly blurred in overview samples ~2.5-10.5 s, while the main face stays clear; blur is absent again by ~11.5 s. Intentional concealment is a hypothesis, not a proven rendering bug. By 23.6/24.6 s the clip is still at the door with continued dialogue/reaction; the reveal does not justify a 25.6 s wait because it already happened at the start.
- **Technical:** 5.332 Mb/s video, -15.3 LUFS, 14.6 LU LRA, -2.2 dBTP. Lowest average bitrate and loudness in the batch, but no measured clipping. Enlarged face detail is visibly soft; deliberate lower-panel blur must not be mistaken for compression.

### 4. `that-was-a-peak-mission_9x16.mp4`

- **Opening/hook:** t=0 is a van driving down a residential road: active, ordinary aftermath. “Team Decoy got away” spans about x=100-980, y=80-190 (~82% width), with top/right UI risk and good outline contrast. Gone at 2 s. Disclosure remains at 2 s and is gone by the ~3.5 s sample.
- **Captions:** standard seam, roughly y=700-780. At 25/26 s “AIN'T NOTHING BUT A” / “WEEKDAY, BABY” remain readable, above bottom UI. The counter's changing lower digits are visibly clipped/competed with near the seam in the overview around 14-18 s. Game dialogue near y=1800 creates a second, much smaller subtitle track under bottom UI.
- **Camera/layout:** 38/62; intact face around a quarter of frame width; count near `652,500`, attribution and mic retained. HUD/status bars also touch the gameplay's top edge beneath the caption line.
- **Pacing/ending:** ~2-5 s establishes escape; much of the rest is driving. The visibly more animated reaction and “peak mission” captions occur ~15-19 s, near the 15.9 s M peak. Midpoint 13.5 s and final 25/26 s are still driving. No mission climax is visible in the sampled sequence; the title describes post-mission praise. Editorial hypothesis: this needs either a stronger preceding action beat or a shorter reaction-focused cut.
- **Technical:** 27 s, highest video bitrate at 12.538 Mb/s; -14.9 LUFS, 4.8 LU LRA, -1.4 dBTP. Bright sunlight at the end reduces local gameplay detail; it does not make the outlined captions unreadable.

### 5. `the-snake-survived-and-has-babies_9x16.mp4`

- **Opening/hook:** dark yard movement, not a loading frame. Gameplay t=0 mean grayscale is **11.9/255; 89.0% of pixels are below 32**, compared with 148.8 mean for the dog clip. Subject recognition is difficult in the viewed frames. “The snake survived?!” spans about x=110-970, y=80-190 (~80% width), readable against darkness but inside top/right UI risk. It disappears by 2 s.
- **Captions:** white/yellow/black styling remains readable at the standard seam. “CHAT MAN WHAT IS” at 0.5-2 s crowds the counter edge; “OH MY GOD HE'S” at midpoint 14.7 s is central. Tiny native dialogue at the bottom of the snake close-up is inside bottom UI coverage.
- **Camera/layout:** 38/62; main face intact at roughly a quarter of frame width, count around `652,610`, attribution and mic retained. The face is much easier to read than the game object because the game scene is so dark.
- **Pacing/ending:** coiled snake becomes clearly featured around ~8-10 s, corresponding to M peak 8.3 s; midpoint shows a larger close-up. “GOT BABIES” / “SHE'S GOT BABIES” appears ~15-19 s. **The babies claim is caption evidence; separate baby snakes were not confidently identifiable visually.** At 27.4/28.4 s the player is already walking away while captions continue. A brighter/closer opening is a hypothesis to test, retaining necessary setup.
- **Technical:** 29.4 s, 6.152 Mb/s video, -14.0 LUFS, 9.2 LU LRA, -1.4 dBTP. Darkness is the dominant visible limitation; bitrate is not demonstrated to be the cause.

### 6. `they-deployed-jets-after-me_9x16.mp4`

- **Opening/hook:** aircraft is clearly visible against clouds at t=0; active and reasonably legible. The opening alone does not show an identifiable pursuing jet. “They deployed JETS” is approximately x=145-935, y=80-190 (~73% width), strong contrast, top overlap and a small right-mask incursion. Gone by 2 s; disclosure remains at 2 s.
- **Captions:** “OH IT HAS A” and “TRACKER ON IT IT” sit at the y~730 seam, with the blue/red gameplay status bar immediately underneath. “DEPLOYED JETS AFTER ME” is central in the ~23.5/24.5 s samples and above the bottom UI. Several overview samples between ~4 and 22 s have no added word captions; without listening this cannot be classified as missing speech.
- **Camera/layout:** 38/62; full face roughly a quarter of width, large mic, count near `652,393-652,398`. The lower face/mic area and retained counter use the edge where subtitles appear. No obvious eye or forehead crop was seen.
- **Pacing/ending:** plane banks and the streamer opens his mouth widely around 21-24 s; M peak 23.6 s corroborates an audio-energy peak there. Viewed thumbnails do not establish the exact pursuer identity/count. At 39.9/40.9 s the plane flies low over water with repeated “GOOD I'M” captions; no crash/resolution is shown before those samples. Hypothesis: shorten the pre-reaction flight and trim repeated reassurance.
- **Technical:** 41.9 s, 7.535 Mb/s video, -15.0 LUFS, 7.3 LU LRA, -1.4 dBTP. No black opening or obvious gross encoding failure observed.

### 7. `this-is-the-best-game-of-all-time_9x16.mp4`

- **Opening/hook:** gunfight is already underway; 0.5 s shows muzzle flash. “Best game of all time” is about 80% frame width, y=80-190, with top/right UI risk. Full contrast is reached by 0.25 s; fading is visible at 1.9 s; absent at 2 s. It is readable but supplies no specific question or surprising event to watch for.
- **Captions:** “NOT YET” at 0.5 s sits on the seam. The title phrase “GAME OF ALL TIME” appears repeatedly ~33-38 s, also at the seam. Added streamer captions are sparse during the gunfight; native game dialogue remains small near the bottom and inside app UI coverage. Whether additional streamer speech lacks captions is unverified.
- **Camera/layout:** 38/62; intact face, mic, attribution and counter `652,480-652,483`; face around a quarter of width. During the late vehicle-interior shots the upper panel retains the streamer while much of the gameplay panel becomes dark cabin space.
- **Pacing/ending:** strong immediate action continues through ~24 s; sampled smiling reaction near 25 s aligns with M peak 25.1 s. Title phrase comes ~33-38 s, during a vehicle/cabin sequence rather than a new action climax. Midpoint 19.1 s is still the gunfight. Final 36.2/37.2 s and additionally viewed 38.15 s show cabin dialogue, not a black tail. Hypothesis: the coda is too long relative to the gunfight's strongest action.
- **Technical:** 38.2 s, 10.936 Mb/s video, -15.1 LUFS, 3.8 LU LRA, -1.4 dBTP. Narrowest loudness range in the batch; this does not establish speech intelligibility.

### 8. `why-is-there-a-bed-in-the-pool_9x16.mp4`

- **Opening/hook:** unusual mattress in a dirty pool is visible at t=0, giving this a specific visual question immediately. Two-line “Why is there a bed in / the pool?” is ~80% width, around y=80-350. First line is in the top mask and extends into the right mask; second line crosses the face around glasses/nose level. Outline contrast is good. Faint hook at 0.05 s, clear by 0.25 s, fading at 1.9 s, absent at 2 s. Disclosure remains through 2.9 s and is absent at 3 s.
- **Captions:** seam-level word captions remain central in the required samples, including “WHY DOES IT HAVE” at 14.5 s and “ON IT OH MY” / “GOD IT'S GOT ROACHES” at 27/28 s. The upper counter is crowded by the caption line. Native game dialogue stretches close to the bottom edge at the opening, inside the bottom mask; the 28.95 s frame also has bottom game dialogue.
- **Camera/layout:** 38/62; full face roughly a quarter of width, counter `651,876-651,879`, attribution and mic retained. Two-line hook plus disclosure uses facial space before the hook disappears. There is no obvious face cutoff in the viewed samples.
- **Pacing/ending:** mattress already visible, but the added premise caption arrives only ~9-11 s. The player approaches and bends down ~17-24 s; “roaches” captions and broad grin arrive ~25-28 s, with M peak at 27.8 s. Actual insects are not confidently resolved from these frames. Last 28.95 s still shows interaction with the mattress, so the late reaction has very little tail before the end. Hypothesis: begin closer to inspection, keeping enough pool context to make the joke clear.
- **Technical:** 29 s, 9.318 Mb/s video, -13.3 LUFS, 12.2 LU LRA, -1.4 dBTP. Loudest integrated level in the batch, but no measured true-peak clipping.

## Eight most frequent or impactful issues, ranked

1. **Hook placement conflicts with the top UI mask: 8/8.** Every first line sits around y=80-190, inside the supplied top 250 px risk zone. Right risk is clear in `he-did-not-expect-who-opened-that-door_9x16.mp4`, `that-was-a-peak-mission_9x16.mp4`, `the-snake-survived-and-has-babies_9x16.mp4`, `this-is-the-best-game-of-all-time_9x16.mp4` and `why-is-there-a-bed-in-the-pool_9x16.mp4`; dog/jets have smaller incursions. Reposition/reflow using an actual UI preview.
2. **Payoff or title fulfillment arrives late: at least 5/8.** Clear dog view ~27-33/44.2 s; robbery ~29-32/37.5 s; jets reaction ~21-24/41.9 s; gunfight title phrase ~33-38/38.2 s; pool roach reaction ~25-28/29 s. These are different beats, but each creates a concrete candidate for a shorter lead-in or tail. Retention impact is a hypothesis.
3. **Retained stream overlays and seam competition: 8/8.** Every facecam retains the subscriber counter and attribution; captions occupy the panel edge. The duplicate camera, clipped follower overlay and red bar in `he-did-not-expect-who-opened-that-door_9x16.mp4` are the worst case. Preserve useful attribution while removing/cropping unrelated overlay clutter in a future edit.
4. **No visible hook at the first decoded frame, with short exposure: 8/8.** Hooks are absent at t=0 and gone by 2 s. Fine samples confirm fades at both ends for `this-is-the-best-game-of-all-time_9x16.mp4` and `why-is-there-a-bed-in-the-pool_9x16.mp4`. Make the initial message immediately readable; exact timing for the other six still needs follow-up if files return.
5. **Weak subject visibility at the opening: severe in snake, material in robbery/dog.** `the-snake-survived-and-has-babies_9x16.mp4` starts with 89% of gameplay pixels below grayscale 32; robbery starts dim with 54.9% below 32; `a-dog-on-a-jet-ski-actually-came_9x16.mp4` starts on swimming with no dog. Choose a recognizable subject frame rather than treating “not black” as sufficient opening quality.
6. **Panel allocation wastes action space: 8/8 have overlay/background overhead; door is the strongest imbalance.** Seven allocate 38% to the upper panel, including much more than face. `he-did-not-expect-who-opened-that-door_9x16.mp4` allocates ~65%, leaving ~35% for the reveal and retaining a second camera. Test a tighter camera crop and an action/reaction-appropriate ratio.
7. **Two-line hooks and opening disclosure crowd the face: clearest in robbery and pool.** “ready” overlays the face in `chat-said-type-1-and-we-robbed-the-store_9x16.mp4`; “the pool?” crosses the face in `why-is-there-a-bed-in-the-pool_9x16.mp4`. Seven clips also show opening `#ad Paid partnership` around y=400-460; the dog clip's viewed opening lacks that text. This is a visual consistency finding, not a determination of disclosure requirements. Reserve separate readable space for required text and expressions.
8. **Native game subtitles are too low and compete with the added subtitle system: clearly visible in at least 6/8.** Bottom dialogue in dog, door, mission, snake, gunfight and pool sits inside the supplied bottom UI mask and is much smaller than word captions; gunfight relies heavily on that small dialogue during action. Door also has an added caption at 12.8 s reaching the right mask. Decide which dialogue viewers need, then present it legibly in the usable area; transcription accuracy remains unverified without listening.
