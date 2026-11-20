from types import SimpleNamespace as P

from autoclip.pipeline.transcript import Transcript, Word
from autoclip.stream import fusion
from autoclip.stream.hype_eval import ViewerClip


def peak(t, score, a, b, why=("x",), sample=()):
    return P(
        t=t,
        score=score,
        window_start=a,
        window_end=b,
        reasons=list(why),
        sample_messages=list(sample),
    )


def test_pool_merges_overlaps_and_respects_cap():
    chat = [peak(100, 5, 70, 110, sample=["a: hi"]), peak(1000, 4, 970, 1010)]
    audio = [peak(105, 3, 75, 115), peak(500, 2, 470, 510)]
    transcript = [peak(900, 1, 770, 910)]  # would merge with chat@1000 only if within cap
    cands = fusion.pool_candidates({"chat": chat, "audio": audio, "transcript": transcript})
    assert [c.id for c in cands] == [1, 2, 3, 4]  # time order
    first = cands[0]
    assert (first.start, first.end) == (70, 115)
    assert set(first.signals) == {"chat", "audio"}
    assert first.chat_sample == ["a: hi"]
    # 770-910 and 970-1010 are 60 s apart: separate with merge_gap 0
    assert all(c.length <= fusion.MAX_WINDOW_S for c in cands)
    assert len(cands) == 4


def test_pool_does_not_exceed_cap():
    a = [peak(100, 1, 0, 100), peak(200, 1, 90, 200)]
    cands = fusion.pool_candidates({"chat": a})
    assert len(cands) == 2


def test_rrf_prefers_multi_signal():
    cands = fusion.pool_candidates(
        {
            "chat": [peak(100, 5, 70, 110), peak(500, 4, 470, 510)],
            "audio": [peak(105, 3, 75, 115), peak(900, 2, 870, 910)],
        }
    )
    top = fusion.rrf_rank(cands, 2)
    assert top[0].t in (100, 105) and len(top) == 2


def test_coverage_union():
    assert fusion.coverage([(0, 10), (5, 15), (100, 110)], 200) == 25 / 200
    assert fusion.coverage([], 100) == 0.0


def test_truth_hits_and_random_baseline():
    clips = [
        ViewerClip(100, 50, duration_s=20),
        ViewerClip(900, 40, duration_s=20),
        ViewerClip(5000, 9),
    ]
    truth = fusion.select_truth(clips, offset_s=0, duration_s=1000, top_clips=10)
    assert len(truth) == 2
    assert fusion.hits(truth, [(60, 90)], overlap=False) == 1  # 100 <= 90+30
    assert fusion.hits(truth, [(0, 10)], overlap=False) == 0
    mean, p95 = fusion.random_baseline(truth, [60] * 5, 1000, overlap=False, sets=200)
    assert 0 < mean < 1 and p95 >= mean
    again = fusion.random_baseline(truth, [60] * 5, 1000, overlap=False, sets=200)
    assert again == (mean, p95)


def test_window_text():
    t = Transcript(words=[Word("a", 0, 1), Word("b", 5, 6), Word("c", 20, 21)])
    assert fusion.window_text(t, 0, 10) == "a b"
