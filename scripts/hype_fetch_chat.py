"""Download chat-only slices of the calibration VOD (no video, no secrets needed).

Usage: python scripts/hype_fetch_chat.py VOD_ID START_H END_H [START_H END_H ...]
Chat JSON is cached by ingest under <root>/streams/<vod>_<start>-<end>/.
"""

import sys

from autoclip.stream import ingest

vod = sys.argv[1]
nums = [float(x) for x in sys.argv[2:]]
for a, b in zip(nums[::2], nums[1::2], strict=True):
    s, e = int(a * 3600), int(b * 3600)
    src = ingest.ingest_twitch_vod(
        f"https://www.twitch.tv/videos/{vod}", start=s, end=e, skip_video=True
    )
    print("done", vod, a, b, src.chat_path, flush=True)
