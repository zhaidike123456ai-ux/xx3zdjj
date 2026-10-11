"""Synthetic opening-review regression; no model or private media required."""
import array
import math
import tempfile
import unittest
import wave
from pathlib import Path

from opening_review import (acoustic_activity, analyze_opening, coverage,
                            execute_opening_review, plan_opening_windows,
                            source_relative_words)


def pcm(duration, bursts):
    samples=array.array('h',[0])*round(duration*16000)
    for start,end in bursts:
        for i in range(round(start*16000),min(len(samples),round(end*16000))):
            samples[i]=round(9000*math.sin(2*math.pi*180*i/16000))
    return samples


class OpeningReviewTests(unittest.TestCase):
    def test_eleven_second_leading_blank_two_short_restarts_are_covered(self):
        samples=pcm(15,[(11.13,11.23),(11.64,12.2)])
        activity=acoustic_activity(samples)
        # Whole-file ASR has swallowed the first sound into one late token.
        plan=plan_opening_windows(15,activity['activity_intervals'],[{'word':'我','start':11.64,'end':12.2}])
        self.assertAlmostEqual(plan['effective_start'],11.13,delta=.011)
        self.assertGreaterEqual(len(plan['windows']),2)
        self.assertTrue(plan['coverage']['complete'])
        self.assertTrue(plan['asr_word_support'])
        for start,end in [(11.13,11.23),(11.64,12.2)]:
            self.assertTrue(any(w['start']<=start and w['end']>=end for w in plan['windows']))
        self.assertLess(plan['activity_gaps'][0]['gap_seconds'],1)
        self.assertFalse(plan['deletion_authorized'])
        self.assertLessEqual(len(plan['windows']),10)
        kinds={w['kind'] for w in plan['windows']}
        self.assertTrue({'isolated_first_activity','second_activity_context','two_activity_context','overlapping_context'}<=kinds)

    def test_earlier_asr_anchor_protects_possible_weak_initial(self):
        plan=plan_opening_windows(20,[{'start':7.16,'end':7.76},{'start':7.81,'end':8.07}],
                                  [{'word':'同','start':6.6,'end':7.04}])
        self.assertAlmostEqual(plan['effective_start'],7.16)
        self.assertAlmostEqual(plan['review_start'],6.6)
        self.assertTrue(any(w['start']<6.6 and w['end']>7.76 for w in plan['windows']))

    def test_location_follows_audio_not_hardcoded_eleven_seconds(self):
        for leading in (.4,7.25,18.4):
            duration=leading+5
            acoustic=acoustic_activity(pcm(duration,[(leading,leading+.1),(leading+.6,leading+1)]))
            plan=plan_opening_windows(duration,acoustic['activity_intervals'],[{'word':'我','start':leading+.6,'end':leading+1}])
            self.assertAlmostEqual(plan['effective_start'],leading,delta=.011)
            self.assertTrue(plan['coverage']['complete'])

    def test_exactly_one_second_gap_is_kept_in_first_word_cluster(self):
        plan=plan_opening_windows(20,[{'start':11,'end':11.1},{'start':12.1,'end':12.4}],
                                  [{'word':'我','start':12.1,'end':12.4}])
        self.assertEqual(plan['effective_start'],11)
        self.assertEqual(len(plan['opening_activity']),2)

    def test_unrelated_early_click_does_not_anchor_first_asr_word(self):
        plan=plan_opening_windows(20,[{'start':.1,'end':.14},{'start':11,'end':11.1},{'start':11.5,'end':12}],
                                  [{'word':'我','start':11.5,'end':12}])
        self.assertEqual(plan['effective_start'],11)

    def test_stretched_asr_token_spanning_leading_blank_prefers_sustained_activity(self):
        plan=plan_opening_windows(20,[{'start':2,'end':2.04},{'start':11.1,'end':11.2},{'start':11.5,'end':12.2}],
                                  [{'word':'我','start':0,'end':12.2}])
        self.assertAlmostEqual(plan['effective_start'],11.1)
        # Timestamp zero is unreliable in this case: do not plan leading blank.
        self.assertTrue(all(w['start']>10 for w in plan['windows']))

    def test_continuous_sound_and_silence_not_invented_as_repeats(self):
        activity=acoustic_activity(pcm(3,[(0,3)]))
        self.assertEqual(len(activity['activity_intervals']),1)
        plan=plan_opening_windows(3,activity['activity_intervals'],[{'word':'正常','start':.1,'end':1}])
        self.assertEqual(plan['effective_start'],0)
        self.assertFalse(plan['activity_gaps'])
        self.assertFalse(plan['speech_verified'])
        quiet=acoustic_activity(pcm(3,[]))
        plan=plan_opening_windows(3,quiet['activity_intervals'])
        self.assertEqual(plan['status'],'skipped')
        self.assertEqual(execute_opening_review(plan)['status'],'skipped')

    def test_missing_callback_reports_unavailable_not_executed(self):
        plan=plan_opening_windows(5,[{'start':1,'end':2}])
        report=execute_opening_review(plan)
        self.assertEqual(report['status'],'unavailable')
        self.assertEqual(report['coverage']['fraction'],0)
        self.assertTrue(report['planned_coverage']['complete'])

    def test_actual_callback_and_time_conversion(self):
        plan=plan_opening_windows(15,[{'start':11.1,'end':12.2}])
        calls=[]
        def callback(window):
            calls.append(window['id'])
            return {'segments':[{'words':[{'word':'我','start':.1,'end':.2}]}]}
        report=execute_opening_review(plan,callback)
        self.assertEqual(report['status'],'executed')
        self.assertEqual(len(calls),len(plan['windows']))
        self.assertTrue(report['coverage']['complete'])
        self.assertAlmostEqual(report['windows'][0]['words'][0]['start'],plan['windows'][0]['start']+.1)
        self.assertEqual(report['human_listening'],'not performed')
        self.assertFalse(report['deletion_authorized'])

    def test_callback_failure_reports_actual_incomplete_coverage(self):
        plan=plan_opening_windows(15,[{'start':11.1,'end':12.2}])
        def callback(window): raise RuntimeError('fixture decoder unavailable')
        report=execute_opening_review(plan,callback)
        self.assertEqual(report['status'],'unavailable')
        self.assertEqual(report['coverage']['fraction'],0)
        self.assertTrue(all(w['status']=='unavailable' for w in report['windows']))

    def test_one_failed_multiscale_window_is_not_hidden_by_full_union_coverage(self):
        plan=plan_opening_windows(15,[{'start':11.1,'end':11.2},{'start':11.5,'end':11.8}])
        def callback(window):
            if window['kind']=='isolated_first_activity':raise RuntimeError('short decode failed')
            return []
        report=execute_opening_review(plan,callback)
        self.assertTrue(report['coverage']['complete'])
        self.assertEqual(report['status'],'unavailable')

    def test_local_words_not_mutated_and_invalid_global_results_rejected(self):
        words=[{'word':'我','start':.1,'end':.2}]
        result=source_relative_words(words,11)
        self.assertEqual(words[0]['start'],.1)
        self.assertEqual(result[0]['start'],11.1)
        plan=plan_opening_windows(15,[{'start':11.1,'end':12.2}])
        report=execute_opening_review(plan,lambda w:[{'word':'我','start':11,'end':12}])
        self.assertEqual(report['status'],'unavailable')

    def test_union_coverage_does_not_count_duplicate_windows_twice(self):
        report=coverage((11,14),[{'start':10,'end':12},{'start':10,'end':12},{'start':11.5,'end':14}])
        self.assertEqual(report['covered_seconds'],3)
        self.assertTrue(report['complete'])

    def test_pcm_wav_contract_and_acoustic_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.wav'
            with wave.open(str(path),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000)
                out.writeframes(pcm(15,[(11.13,11.23),(11.64,12.2)]).tobytes())
            report=analyze_opening(path,[{'word':'我','start':11.64,'end':12.2}])
            self.assertTrue(report['wav_sha256'])
            self.assertAlmostEqual(report['effective_start'],11.13,delta=.011)
            self.assertIn('activity_threshold_dbfs',report['acoustic_evidence'])
            self.assertTrue(report['acoustic_evidence']['frames'])
            self.assertFalse(report['acoustic_evidence']['speech_verified'])

    def test_invalid_window_parameters_block(self):
        with self.assertRaises(ValueError):plan_opening_windows(10,[{'start':1,'end':2}],window_seconds=2,hop_seconds=2)
        with self.assertRaises(ValueError):acoustic_activity([0],sample_rate=48000)


if __name__=='__main__':unittest.main()
