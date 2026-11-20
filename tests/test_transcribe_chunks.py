import wave

import numpy as np
from autoclip.pipeline import transcribe


def _wav(path, seconds, rate=16000, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.zeros(seconds * rate * channels, dtype=np.int16)).tobytes())
    return path


def test_long_wav_is_split_into_offset_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe, "CHUNK_THRESHOLD_S", 2)
    monkeypatch.setattr(transcribe, "CHUNK_S", 2)
    chunks = list(transcribe._audio_chunks(_wav(tmp_path / "a.wav", 5)))
    assert [off for off, _ in chunks] == [0.0, 2.0, 4.0]
    assert [len(c) for _, c in chunks] == [32000, 32000, 16000]
    assert chunks[0][1].dtype == np.float32


def test_short_or_unsupported_audio_is_not_chunked(tmp_path):
    short = _wav(tmp_path / "s.wav", 3)
    assert list(transcribe._audio_chunks(short)) == [(0.0, str(short))]
    stereo = _wav(tmp_path / "st.wav", 3, channels=2)
    assert list(transcribe._audio_chunks(stereo)) == [(0.0, str(stereo))]
    other = tmp_path / "x.mp3"
    other.write_bytes(b"not a wav")
    assert list(transcribe._audio_chunks(other)) == [(0.0, str(other))]
