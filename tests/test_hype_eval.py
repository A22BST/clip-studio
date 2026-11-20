from autoclip.stream.hype_eval import ViewerClip, hit_rate


def test_hit_rate_counts_clips_inside_windows_with_tolerance():
    clips = [ViewerClip(100, 50), ViewerClip(500, 40), ViewerClip(900, 30), ViewerClip(5000, 99)]
    windows = [(90.0, 120.0), (470.0, 480.0)]
    rate, details = hit_rate(clips, windows, top_clips=3, tolerance_s=30)
    # top 3 by views: 5000 (miss), 100 (hit), 500 (hit, 20s beyond window end)
    assert rate == 2 / 3
    assert [hit for _, hit in details] == [False, True, True]


def test_offset_and_range_filter_for_trimmed_downloads():
    clips = [ViewerClip(10_900, 10), ViewerClip(100, 90), ViewerClip(20_000, 80)]
    rate, details = hit_rate(clips, [(80.0, 120.0)], offset_s=10_800, max_s=1800, tolerance_s=0)
    assert len(details) == 1 and rate == 1.0 and details[0][0].offset_s == 100


def test_no_clips_gives_zero():
    assert hit_rate([], [(0, 1)])[0] == 0.0


def test_user_env_prefers_process_env_and_never_raises(monkeypatch):
    from autoclip.stream.hype_eval import user_env

    monkeypatch.setenv("CLIPSTUDIO_TEST_VAR", "abc")
    assert user_env("CLIPSTUDIO_TEST_VAR") == "abc"
    assert user_env("CLIPSTUDIO_SURELY_UNSET_VAR_12345") is None


def test_overlap_mode_counts_clip_span_not_just_its_start():
    clip = [ViewerClip(100.0, 10, "x", 30.0)]  # clip spans 100-130 s
    windows = [(150.0, 170.0)]
    assert hit_rate(clip, windows, tolerance_s=10)[0] == 0.0  # start point is 40 s away
    assert hit_rate(clip, windows, tolerance_s=25, overlap=True)[0] == 1.0  # span reaches 125
    assert hit_rate(clip, windows, tolerance_s=10, overlap=True)[0] == 0.0
