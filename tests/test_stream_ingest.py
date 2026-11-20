import json

import pytest
from autoclip.stream import ingest
from autoclip.stream.chat import ChatLog, parse_twitchdownloader_json

RAW = {
    "streamer": {"name": "teststreamer", "id": 1},
    "video": {"id": "2000000001", "start": 0, "end": 120, "length": 120, "title": "GTA 6 day 2"},
    "comments": [
        {
            "content_id": "2000000001",
            "content_offset_seconds": 12.5,
            "commenter": {"display_name": "Bob", "name": "bob"},
            "message": {
                "body": "KEKW no way",
                "fragments": [
                    {"text": "KEKW ", "emoticon": {"emoticonId": "1"}},
                    {"text": "no way"},
                ],
            },
        },
        {"content_offset_seconds": 3.0, "commenter": {"name": "amy"}, "message": {"body": "hi"}},
        {"broken": True},
    ],
}


def test_parse_sorts_skips_bad_and_reads_emotes():
    log = parse_twitchdownloader_json(RAW)
    assert [m.t for m in log.messages] == [3.0, 12.5]
    assert log.messages[1].emotes == ["KEKW "] or log.messages[1].emotes == ["KEKW"]
    assert log.streamer == "teststreamer" and log.duration_s == 120 and log.video_id == "2000000001"


def test_shifted_drops_negative_and_roundtrips(tmp_path):
    log = parse_twitchdownloader_json(RAW).shifted(-5.0)
    assert [m.t for m in log.messages] == [7.5]
    saved = ChatLog.load(log.save(tmp_path / "c.json"))
    assert saved.messages[0].text == "KEKW no way"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.twitch.tv/videos/2000000001", "2000000001"),
        ("https://www.twitch.tv/videos/2000000001?filter=archives", "2000000001"),
        ("2000000001", "2000000001"),
        ("https://youtube.com/watch?v=abc", None),
        ("C:/videos/stream.mp4", None),
    ],
)
def test_twitch_vod_id(url, expected):
    assert ingest.twitch_vod_id(url) == expected


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("90", 90), ("1:30", 90), ("1:02:03", 3723), ("1h2m3s", 3723), ("", 0), (None, 0)],
)
def test_parse_time(text, seconds):
    assert ingest.parse_time(text) == seconds


def test_parse_time_rejects_garbage():
    with pytest.raises(ingest.StreamIngestError):
        ingest.parse_time("soon")


def test_ingest_local_stores_video_and_aligned_chat(tmp_path, monkeypatch):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg missing")
    import subprocess

    monkeypatch.setenv("AUTOCLIP_HOME", str(tmp_path / "home"))
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=d=2:s=320x180",
         "-f", "lavfi", "-i", "sine=d=2", "-shortest", str(video)],
        check=True,
    )  # fmt: skip
    chat = tmp_path / "chat.json"
    chat.write_text(json.dumps(RAW), encoding="utf-8")
    source = ingest.ingest_local(video, chat_json=chat, vod_id="t1")
    assert source.video.exists() and source.chat_path and source.chat_path.exists()
    assert source.load_chat().duration_s == pytest.approx(source.duration_s)
    assert ingest.load_stream("t1").vod_id == "t1"
