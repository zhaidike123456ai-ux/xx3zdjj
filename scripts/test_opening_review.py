"""Synthetic opening-review regression; no model or private media required."""
import array
import copy
import json
import math
import tempfile
import unittest
import wave
from pathlib import Path

from opening_review import (acoustic_activity, analyze_opening, coverage,
                            execute_opening_review, plan_opening_windows,
                            source_relative_word_evidence, source_relative_words)


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
        self.assertTrue(report['temporal_coverage_complete'])
        self.assertFalse(report['multiscale_complete'])
        self.assertEqual(report['failed_windows'],1)
        self.assertEqual(report['completed_windows'],report['scheduled_windows']-1)
        self.assertEqual(report['quality_status'],'review_required')

    def test_exact_eight_window_union_coverage_does_not_hide_one_failed_scale(self):
        windows=[{'id':f'window_{index}','start':10.,'end':12.5,'kind':'overlapping_context'}
                 for index in range(8)]
        windows[0].update(start=11.1,end=11.6,kind='isolated_first_activity')
        plan={'windows':windows,'coverage':coverage((10.,12.5),windows),'media_duration':15.}
        def callback(window):
            if window['id']=='window_0':raise RuntimeError('fixture failed scale')
            return [{'word':'我','start':.1,'end':.2}]
        result=execute_opening_review(plan,callback)
        self.assertEqual((result['scheduled_windows'],result['completed_windows'],result['failed_windows']),
                         (8,7,1))
        self.assertTrue(result['temporal_coverage_complete'])
        self.assertFalse(result['multiscale_complete'])
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['quality_status'],'review_required')

    def test_nine_valid_words_survive_tenth_zero_duration_word(self):
        words=[{'word':character,'start':.2*index,'end':.2*index+.1,'probability':.9}
               for index,character in enumerate('不知道這個玩法只要')]
        words.append({'word':'上','start':2.48,'end':2.48,'probability':.7})
        before=copy.deepcopy(words)
        result=source_relative_word_evidence(words,13.23,window_end=15.73,window_id='zero_tail')
        self.assertEqual(words,before,'validation must not mutate decoder output')
        self.assertEqual(result['raw_words'],before)
        self.assertEqual(len(result['words']),9)
        self.assertEqual(len(result['timing_unverified']),1)
        issue=result['timing_unverified'][0]
        self.assertEqual((issue['window_id'],issue['index'],issue['word']),('zero_tail',9,'上'))
        self.assertEqual((issue['local_start'],issue['local_end']),(2.48,2.48))
        self.assertAlmostEqual(issue['source_start'],15.71)
        self.assertEqual(issue['source_start'],issue['source_end'],'zero span must not receive invented duration')
        self.assertFalse(issue['usable_for_cut']);self.assertFalse(issue['usable_for_subtitle_timing'])
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['quality_status'],'review_required')
        self.assertTrue(all(w['source_word_index']<9 for w in result['words']))

    def test_zero_duration_window_keeps_full_transcript_and_specific_indices(self):
        decoded={'language':'zh','segments':[{'text':'不知道這個玩法只要在圖片上',
                 'words':[{'word':'不知道','start':.1,'end':.8},
                          {'word':'上','start':2.48,'end':2.48}]}]}
        window={'id':'affected_window','start':13.23,'end':15.73,'kind':'overlapping_context'}
        plan={'windows':[window],'coverage':coverage((13.23,15.73),[window]),'media_duration':20.}
        result=execute_opening_review(plan,lambda window:decoded)
        row=result['windows'][0]
        self.assertEqual(row['raw_output'],decoded)
        self.assertEqual(len(row['words']),1)
        issue=row['timing_unverified'][0]
        self.assertEqual((issue['segment_index'],issue['segment_word_index']),(0,1))
        self.assertIn('word 1',row['reason']);self.assertIn('上',row['reason'])
        self.assertEqual(result['quality_status'],'review_required')
        self.assertFalse(result['multiscale_complete'])

    def test_malformed_decoder_output_retained_and_not_relabelled_as_timing_only(self):
        malformed={'segments':'not-a-list','text':'我我发现'}
        plan=plan_opening_windows(5,[{'start':1,'end':2}])
        report=execute_opening_review(plan,lambda w:malformed)
        self.assertEqual(report['status'],'unavailable')
        self.assertEqual(report['quality_status'],'review_required')
        for row in report['windows']:
            self.assertEqual(row['raw_output'],malformed)
            self.assertEqual(row['error_type'],'ValueError')
            self.assertFalse(row['timing_unverified'])
        self.assertFalse(report['temporal_coverage_complete'])

    def test_one_retry_has_new_interval_and_original_failure_is_not_erased(self):
        plan=plan_opening_windows(5,[{'start':1,'end':2}])
        calls=[]
        first_id=plan['windows'][0]['id']
        def callback(window):
            calls.append(copy.deepcopy(window))
            if window['id']==first_id:return [{'word':'我','start':.2,'end':.2}]
            return [{'word':'我','start':.2,'end':.4}]
        result=execute_opening_review(plan,callback,max_retries=1)
        self.assertEqual(len(calls),len(plan['windows'])+1)
        self.assertEqual(result['retried_windows'],1)
        self.assertEqual(result['successful_retries'],1)
        first=result['windows'][0];retry=result['retry_windows'][0]
        self.assertEqual(first['status'],'unavailable')
        self.assertEqual(retry['status'],'executed')
        self.assertEqual(retry['retry_of'],first_id)
        self.assertNotEqual((retry['start'],retry['end']),(first['start'],first['end']))
        self.assertEqual(retry['cache_window'],[retry['start'],retry['end']])
        self.assertGreaterEqual(retry['start'],0);self.assertLessEqual(retry['end'],plan['media_duration'])
        self.assertEqual(result['failed_windows'],1)
        self.assertFalse(result['multiscale_complete'])
        self.assertEqual(result['quality_status'],'review_required')
        self.assertTrue(first['timing_unverified'])

    def test_retry_is_total_budget_and_disabled_by_default(self):
        plan=plan_opening_windows(15,[{'start':11.1,'end':11.2},{'start':11.5,'end':11.8}])
        def fail(window):raise RuntimeError('decoder fixture failure')
        self.assertEqual(execute_opening_review(plan,fail)['retried_windows'],0)
        result=execute_opening_review(plan,fail,max_retries=1)
        self.assertEqual(result['retried_windows'],1)
        self.assertEqual(result['failed_windows'],result['scheduled_windows'])
        self.assertEqual(result['successful_retries'],0)
        for invalid in (-1,2,True,1.0):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                execute_opening_review(plan,fail,max_retries=invalid)

    def test_chinese_word_evidence_utf8_roundtrip(self):
        words=[{'word':'正常词','start':.1,'end':.3},{'word':'上','start':.4,'end':.4}]
        evidence=source_relative_word_evidence(words,1,window_end=2,window_id='utf8')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'word_evidence.json'
            path.write_text(json.dumps(evidence,ensure_ascii=False,allow_nan=False),encoding='utf-8')
            restored=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(restored['words'][0]['word'],'正常词')
        self.assertEqual(restored['timing_unverified'][0]['word'],'上')

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

    def test_padded_wav_planning_uses_media_bounds_preserves_raw_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'padded_fixture.wav'
            with wave.open(str(path),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000)
                out.writeframes(pcm(24.064,[(23.98,24.064)]).tobytes())
            report=analyze_opening(path,media_duration=24.05)
            self.assertEqual(report['media_duration'],24.05)
            self.assertEqual(report['acoustic_evidence']['duration'],24.064)
            self.assertTrue(report['windows'])
            self.assertTrue(all(0<=w['start']<w['end']<=24.05 for w in report['windows']))
            self.assertTrue(all(x['end']<=24.05 for x in report['opening_activity']))
            self.assertTrue(report['coverage']['complete'])

    def test_invalid_window_parameters_block(self):
        with self.assertRaises(ValueError):plan_opening_windows(10,[{'start':1,'end':2}],window_seconds=2,hop_seconds=2)
        with self.assertRaises(ValueError):acoustic_activity([0],sample_rate=48000)


if __name__=='__main__':unittest.main()
