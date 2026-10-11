from run_pipeline import fragment_restart_candidates, repeated_phrases, frame_safe_retake_cut_start


def words(chars, starts, ends):
    return [{"word":c,"start":s,"end":e,"probability":0.99}
            for c,s,e in zip(chars,starts,ends)]


def test_explicit_half_sentence_restart():
    chars=list("而是你的提而是你的提示词里")
    starts=[i*0.18 for i in range(len(chars))]
    ends=[s+0.16 for s in starts]
    found=fragment_restart_candidates(words(chars,starts,ends))
    assert any(x["content"]=="而是你的提" and x["start"]==0 for x in found)


def test_swallowed_restart_long_token_is_reviewed():
    found=fragment_restart_candidates(words(["而","是","你的"],[7.54,7.64,9.32],[7.64,9.32,9.60]))
    assert any("swallowed restart" in x["evidence"] and x["content"]=="是" for x in found)


def test_adjacent_complete_phrase_retake():
    chars=list("人物做什么光从哪来人物做什么光从哪来")
    starts=[i*0.20 for i in range(len(chars))]
    # Leave a positive 40 ms boundary so the second take is distinguished.
    ends=[s+0.16 for s in starts]
    found=repeated_phrases(words(chars,starts,ends))
    assert any(x["phrase"].startswith("人物做什么") and "光从哪" in x["phrase"] for x in found)


def test_failed_first_syllable_uses_acoustic_onset_not_late_asr_start():
    # Real regression: acoustic onset was about 7.39, while ASR exposed the
    # token at 7.54. A 60 fps cut must land before the acoustic onset.
    cut=frame_safe_retake_cut_start(7.32,7.39,60)
    assert cut==443/60
    assert cut < 7.39 < 7.54


def test_short_opening_restart_is_detected():
    chars=["当","你","当","你","不","小心","在","GPT","里"]
    starts=[17.72,18.08,18.44,18.68,18.86,19.04,19.34,19.66,20.08]
    ends=[18.08,18.28,18.68,18.86,19.04,19.34,19.66,20.08,20.22]
    found=fragment_restart_candidates(words(chars,starts,ends))
    assert any(x["content"]=="当你" and abs(x["end"]-18.44)<1e-9 for x in found)


def test_partial_middle_attempt_before_last_complete_take():
    chars=["你","把它","加","你","把它","加","到","对话框","里"]
    starts=[38.06,38.50,38.80,39.22,39.42,39.74,39.92,40.14,40.60]
    ends=[38.50,38.80,39.04,39.42,39.74,39.92,40.14,40.60,40.82]
    found=fragment_restart_candidates(words(chars,starts,ends))
    assert any(x["content"]=="你把它加" and abs(x["end"]-39.22)<1e-9 for x in found)


def test_complete_take_repeated_with_failed_single_word_between():
    chars=["你","惊","讶","地","发","现","你","你","惊","讶","地","发","现"]
    starts=[45.8,46.02,46.14,46.24,46.48,46.60,49.84,50.52,50.84,50.98,51.08,51.24,51.44]
    ends=[46.02,46.14,46.24,46.48,46.60,46.84,49.94,50.84,50.98,51.08,51.24,51.44,51.64]
    found=repeated_phrases(words(chars,starts,ends))
    assert any("你惊讶地发现" in x["phrase"] for x in found)


def test_one_token_restart_and_swallowed_single_token():
    found=fragment_restart_candidates(words(["我","我","发现"],[0,.24,.5],[.2,.48,.9]))
    assert any(x["content"]=="我" and x["start"]==0 for x in found)
    found=fragment_restart_candidates(words(["我我","发现"],[0,.5],[.48,.9]))
    assert any("inside one ASR token" in x["evidence"] for x in found)
    assert all("cut" not in x or not x["cut"] for x in found)


def test_normal_shared_suffix_not_repeat():
    found=fragment_restart_candidates(words(["远景","中景","特写"],[0,.5,1],[.4,.9,1.4]))
    assert not found
    # Lexical reduplication is deliberately a candidate, never a deletion.
    lexical=fragment_restart_candidates(words(["看看"],[0],[.4]))
    assert lexical and "no inferred intra-token cut" in lexical[0]["status"]


def load_tests(loader, tests, pattern):
    """Include historical function regressions in unittest discovery."""
    import unittest
    return unittest.TestSuite(unittest.FunctionTestCase(value) for name,value in sorted(globals().items())
                              if name.startswith('test_') and callable(value))


if __name__ == "__main__":
    test_explicit_half_sentence_restart()
    test_swallowed_restart_long_token_is_reviewed()
    test_adjacent_complete_phrase_retake()
    test_failed_first_syllable_uses_acoustic_onset_not_late_asr_start()
    test_short_opening_restart_is_detected()
    test_partial_middle_attempt_before_last_complete_take()
    test_complete_take_repeated_with_failed_single_word_between()
    test_one_token_restart_and_swallowed_single_token()
    test_normal_shared_suffix_not_repeat()
    print("retake detection regression: PASS")
