from autoclip.pipeline.cutqa import compare_edge


def test_clean_start_and_end():
    assert compare_edge(["no", "way", "that", "happened"], ["No", "way", "that"], "start") is None
    assert compare_edge(["so", "that", "happened"], ["so", "that", "happened."], "end") is None


def test_start_swallowed_first_word_is_error():
    issue = compare_edge(["no", "way", "that", "happened"], ["way", "that", "happened"], "start")
    assert issue and issue.severity == "error" and "cut off" in issue.message


def test_end_swallowed_last_word_is_error():
    issue = compare_edge(["and", "then", "he", "died"], ["and", "then", "he"], "end")
    assert issue and issue.severity == "error"


def test_unrelated_words_only_warn():
    issue = compare_edge(["hello", "there", "chat"], ["xylophone", "music"], "start")
    assert issue and issue.severity == "warning"


def test_silence_or_nothing_expected_is_fine():
    assert compare_edge(["hello", "chat"], [], "start") is None
    assert compare_edge([], ["hello"], "end") is None


def test_fuzzy_match_tolerates_whisper_spelling():
    assert compare_edge(["gonna", "win"], ["gunna", "win"], "start") is None
