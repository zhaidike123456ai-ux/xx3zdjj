"""Independent deterministic pipeline regression; no model, real media or UI.

Mocks external recognition/FFmpeg, while checking generated proposals, dispatch
and actual frame-quantized boundary decisions. State-machine details are tested
separately in test_review_state.py. Fixtures cannot prove real listening quality.
"""
import argparse
from contextlib import redirect_stdout
import csv
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import run_pipeline as pipeline


def word(text,start,end):
    return dict(word=text,start=start,end=end,probability=.99)


def transcript(words):
    return {'segments':[{'start':words[0]['start'],'end':words[-1]['end'],'text':''.join(w['word'] for w in words),'words':words}]}


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


class DetectionPolicyTests(unittest.TestCase):
    def test_default_policy_none_does_not_disable_detection(self):
        received=[]
        with patch.object(pipeline,'analyze',side_effect=lambda args: received.append(args) or 0), patch.object(pipeline.sys,'argv',['run_pipeline.py','analyze','--source','fixture.mp4','--output-dir','fixture-out']):
            self.assertEqual(pipeline.main(),0)
        self.assertEqual(received[0].retake_policy,'none')
        segments=[]
        for offset in [0,6]:
            segments.extend([{'start':offset,'end':offset+2,'text':'我发现很多人还不知道这个玩法'},
                             {'start':offset+2,'end':offset+4,'text':'只要画出飞行路线就可以生成视频'}])
        candidates=pipeline.detect_retake_groups(segments,'none')
        self.assertTrue(candidates,'none is a deletion policy, never a detection-disable flag')
        self.assertTrue(all(not x['proposed_delete_start'] and not x['proposed_delete_end'] for x in candidates))
        self.assertTrue(any(x['proposed_delete_start'] for x in pipeline.detect_retake_groups(segments,'last_complete')))

    def test_legacy_long_token_alerts_in_both_policies_without_auto_cut(self):
        segments=transcript([word('我',.2,1.4),word('发现',1.4,1.8)])['segments']
        for policy in ['none','last_complete']:
            with self.subTest(policy=policy):
                rows=pipeline.detect_opening_swallowed_restarts(segments,[],[],policy,30)
                self.assertTrue(rows)
                self.assertTrue(all(x['decision']=='local_audio_review_required' for x in rows))
                self.assertTrue(all(not x['proposed_delete_start'] and not x['proposed_delete_end'] for x in rows))

    def test_single_word_repeat_requires_review_not_a_phoneme_cut(self):
        rows=pipeline.fragment_restart_candidates([word('我',.1,.3),word('我',.4,.6),word('发现',.6,.9)])
        self.assertTrue(rows)
        self.assertTrue(all('proposed_delete_start' not in x for x in rows))

    def test_lexical_reduplicated_words_remain_review_only(self):
        for text in ['看看','斜斜','慢慢']:
            with self.subTest(text=text):
                rows=pipeline.fragment_restart_candidates([word(text,.1,.5)])
                self.assertTrue(rows)
                self.assertTrue(all('local audio review required' in x['status'] for x in rows))
                self.assertTrue(all('delete_start' not in x and 'proposed_delete_start' not in x for x in rows))

    def test_normal_nonrepeated_negative_condition_not_a_fragment_retry(self):
        words=[word('如果',.1,.3),word('不是',.3,.5),word('同一个',.5,.8),word('距离',.8,1.1)]
        self.assertEqual(pipeline.fragment_restart_candidates(words),[])


class AnalysisIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='retake-pipeline-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source.mp4';self.source.write_bytes(b'SYNTHETIC source identity only')
        self.out=self.root/'analysis'
        self.meta={'format':{'duration':'5.0'},'streams':[{'codec_type':'video','r_frame_rate':'30/1','width':180,'height':320},{'codec_type':'audio'}]}

    def args(self,**values):
        defaults=dict(source=self.source,output_dir=self.out,resume=False,silence_noise='-42dB',silence_min=.35,
                      model='synthetic-model-not-loaded',single_pass=True,retake_policy='none',propose_internal=1.2,low_confidence=.55,cpu_threads=1)
        defaults.update(values);return argparse.Namespace(**defaults)

    def extract(self,source,path):
        with wave.open(str(path),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(b'\0\0'*80000)

    def analyze(self,words,silences=None,opening=None,single_pass=True):
        silences=silences or []
        opening=opening if opening is not None else {'status':'executed','reason':'synthetic opening review callback',
                      'coverage':{'scope':'opening_windows','start':0,'end':1},
                      'alerts':[{'check_id':'repeated_speech','start':.1,'end':.6,'text':'我 我发现','kind':'opening_fixture','review_required':True}],
                      'windows':[],'plan':{},'human_listening':'not performed'}
        with patch.object(pipeline,'probe',return_value=self.meta), patch.object(pipeline,'extract_audio',side_effect=self.extract), \
             patch.object(pipeline,'run',return_value=SimpleNamespace(stdout='',stderr='')), \
             patch.object(pipeline,'parse_silence',side_effect=[silences,silences]), \
             patch.object(pipeline,'cached_recognition',return_value=transcript(words)) as recognizer, \
             patch.object(pipeline,'opening_audit',return_value=opening,create=True) as auditor, \
             patch.dict(pipeline.os.environ,{'XX3ZDJJ_FFMPEG':'mock-ffmpeg','XX3ZDJJ_FFPROBE':'mock-ffprobe'}), \
             redirect_stdout(io.StringIO()) as stdout:
            result=pipeline.analyze(self.args(single_pass=single_pass))
        return result,auditor,recognizer,stdout.getvalue()

    def test_single_pass_still_runs_independent_opening_audit(self):
        result,auditor,recognizer,output=self.analyze([word('我',.2,.45),word('发现',.45,.8)],single_pass=True)
        self.assertEqual(result,0)
        self.assertEqual(recognizer.call_count,1)
        auditor.assert_called_once()
        self.assertEqual(Path(auditor.call_args.args[0]).resolve(),self.source.resolve())
        self.assertFalse(any(p.name.startswith('rough') for p in self.out.iterdir()))
        report=json.loads((self.out/'review-report.json').read_text(encoding="utf-8"))
        self.assertEqual(report['detection_checks']['second_full_asr']['status'],'skipped')
        self.assertEqual(report['detection_checks']['opening_overlap']['status'],'executed')
        self.assertEqual(report['command_status'],'completed')
        self.assertEqual(report['quality_status'],'review_required')
        self.assertEqual(report['source_sha256'],pipeline.sha256(self.source))

    def test_two_full_passes_do_not_replace_independent_opening_audit(self):
        _,auditor,recognizer,_=self.analyze([word('我',.2,.45),word('发现',.45,.8)],single_pass=False)
        self.assertEqual(recognizer.call_count,2);auditor.assert_called_once()

    def test_policy_none_writes_fragment_review_warning(self):
        self.analyze([word('我',.1,.3),word('我',.4,.6),word('发现',.6,.9)])
        decisions=read_csv(self.out/'deletion-decisions.csv')
        rows=[x for x in decisions if x['candidate_type']=='short_fragment_or_swallowed_restart']
        self.assertTrue(rows)
        self.assertTrue(all(x['program_decision'] in ('local_audio_review_required','evidenced_semantic_and_acoustic_review_required') for x in rows))
        self.assertTrue(all(not x['delete_start'] and not x['delete_end'] for x in rows))

    def test_zero_machine_candidate_is_not_a_quality_pass(self):
        self.analyze([word('如果',.1,.3),word('人物',.3,.5)],opening={'status':'executed','reason':'mock no candidate','coverage':{'scope':'opening_windows','start':0,'end':1},'alerts':[],'windows':[],'plan':{}})
        report=json.loads((self.out/'review-report.json').read_text(encoding="utf-8"))
        self.assertEqual(report['alerts'],[])
        self.assertEqual(report['command_status'],'completed')
        self.assertEqual(report['quality_status'],'unverified')
        self.assertEqual(report['checks']['word_integrity']['result'],'unverified')
        self.assertEqual(report['checks']['word_integrity']['status'],'executed')
        self.assertEqual(report['checks']['word_integrity']['machine_scope']['usable_words'],2)
        self.assertIs(report['checks']['word_integrity']['optional_listening']['required'],False)

    def test_bad_word_times_remain_unavailable_with_tracked_alerts(self):
        self.analyze([word('如果',.1,.3),word('人物',.3,.3)],opening={'status':'executed','reason':'mock complete opening','alerts':[],'windows':[],'plan':{}})
        report=json.loads((self.out/'review-report.json').read_text(encoding='utf-8'))
        check=report['checks']['word_integrity']
        self.assertEqual(check['status'],'unavailable')
        self.assertEqual(check['result'],'review_required')
        self.assertEqual(check['machine_scope']['usable_words'],1)
        self.assertEqual(check['machine_scope']['timing_unverified_words'],1)
        self.assertTrue(any(x.get('evidence',{}).get('timing_status')=='timing_unverified' for x in report['alerts']))
        self.assertEqual(report['quality_status'],'review_required')

    def test_opening_unavailable_stays_explicit_unverified(self):
        self.analyze([word('如果',.1,.3)],opening={'status':'unavailable','reason':'decoder unavailable fixture','coverage':{},'alerts':[],'windows':[],'plan':{}})
        report=json.loads((self.out/'review-report.json').read_text(encoding="utf-8"))
        self.assertEqual(report['detection_checks']['opening_overlap']['status'],'unavailable')
        self.assertIn('decoder unavailable',report['detection_checks']['opening_overlap']['reason'])
        self.assertEqual(report['quality_status'],'unverified')
        self.assertEqual(report['checks']['word_integrity']['status'],'unavailable')
        self.assertIn('effective opening review incomplete',report['checks']['word_integrity']['reason'])

    def test_opening_short_activity_is_reviewed_even_if_global_asr_merged_it(self):
        self.out.mkdir()
        plan={'status':'ready','acoustic_evidence':{'duration':5},'opening_activity':[{'start':.2,'end':.4},{'start':.5,'end':.9}],'windows':[]}
        result={'status':'executed','reason':'mock window decoding','coverage':{},'windows':[{'words':[word('我',.2,.4)]}]}
        with patch.object(pipeline,'analyze_opening',return_value=plan),patch.object(pipeline,'execute_opening_review',return_value=result):
            actual=pipeline.opening_audit(self.source,self.root/'synthetic.wav',self.out,self.args(),[word('我',.2,.6)],decoder=lambda window: {})
        self.assertTrue(any(x['kind']=='opening_short_activity' for x in actual['alerts']))
        self.assertTrue(all(x['review_required'] for x in actual['alerts']))
        self.assertTrue(all('delete_start' not in x for x in actual['alerts']))
        self.assertTrue((self.out/'opening-review.json').is_file())

    def test_wrong_asr_first_word_cannot_expand_leading_silence(self):
        self.analyze([word('已经漏了开头',2,2.6)],silences=[dict(start=0,end=.3,duration=.3)])
        row=read_csv(self.out/'silence-candidates.csv')[0]
        self.assertEqual(float(row['proposed_delete_start']),0)
        self.assertLessEqual(float(row['proposed_delete_end']),.3)
        self.assertLess(float(row['proposed_delete_end']),2-.12)

    def test_wrong_asr_last_word_cannot_expand_trailing_silence(self):
        self.analyze([word('已经漏了尾词',.8,2)],silences=[dict(start=4.5,end=5,duration=.5)])
        row=read_csv(self.out/'silence-candidates.csv')[0]
        self.assertGreaterEqual(float(row['proposed_delete_start']),4.5)
        self.assertEqual(float(row['proposed_delete_end']),5)


class AlertLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='retake-lineage-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.media=self.root/'rough.mp4';self.media.write_bytes(b'SYNTHETIC output bytes')
        self.original=self.root/'original.mp4';self.original.write_bytes(b'SYNTHETIC original bytes')

    def test_conflicting_explicit_ids_must_not_silently_overwrite(self):
        a={'id':'same-id','check_id':'repeated_speech','start':.1,'end':.3,'kind':'opening','text':'我','review_required':True}
        b={**a,'end':.8,'text':'我发现'}
        with self.assertRaisesRegex(ValueError,'conflicting|silently'):
            pipeline.unique_alerts(self.media,[a,b])
        self.assertEqual(len(pipeline.unique_alerts(self.media,[a,dict(a)])),1)

    def test_distinct_upstream_alerts_with_same_text_and_output_span_survive(self):
        report=self.root/'source-review.json'
        report.write_text(json.dumps({'source_sha256':pipeline.sha256(self.original),'alerts':[
            {'id':'upstream-one','check_id':'repeated_speech','start':.2,'end':.4,'text':'我','review_required':True},
            {'id':'upstream-two','check_id':'repeated_speech','start':.5,'end':.7,'text':'我','review_required':True}]}), encoding="utf-8")
        # Both removed source ranges map to the exact same retained cut boundary.
        mapping={'output_sha256':pipeline.sha256(self.media),'source_sha256':pipeline.sha256(self.original),
                 'analysis_review':{'path':str(report),'sha256':pipeline.sha256(report)},
                 'kept_segments':[{'source_start':2,'source_end':3,'output_start':0,'output_end':1}]}
        (self.root/'edit-map.json').write_text(json.dumps(mapping), encoding="utf-8")
        alerts,lineage=pipeline.propagate_analysis_alerts(self.media,1)
        self.assertEqual(lineage['status'],'executed')
        self.assertEqual(len(alerts),2)
        self.assertEqual([(a['start'],a['end']) for a in alerts],[(0,.5),(0,.5)])
        self.assertEqual({a['upstream_alert_id'] for a in alerts},{'upstream-one','upstream-two'})
        self.assertEqual(len({a['id'] for a in alerts}),2)
        self.assertEqual(len(pipeline.unique_alerts(self.media,alerts)),2)

    def test_changed_output_rejects_existing_lineage(self):
        (self.root/'edit-map.json').write_text(json.dumps({'output_sha256':'stale'}), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit,'another output'):
            pipeline.propagate_analysis_alerts(self.media,1)


class RoughCutBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='retake-cut-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source.mp4';self.source.write_bytes(b'SYNTHETIC source identity only')
        self.analysis=self.root/'analysis';self.analysis.mkdir();self.out=self.root/'cut'
        self.source_hash=pipeline.sha256(self.source)
        (self.analysis/'analysis-manifest.json').write_text(json.dumps({'source_sha256':self.source_hash}), encoding="utf-8")
        self.meta={'format':{'duration':'5.0'},'streams':[{'codec_type':'video','r_frame_rate':'30/1','width':180,'height':320},{'codec_type':'audio'}]}
        self.decision=self.root/'decisions.csv';self.evidence=self.root/'bounds.json'
        self.row=dict(candidate_id='RT001',candidate_type='long_sentence_retake',delete_start='.5',delete_end='1.019',
                      program_decision='resolved_delete',acoustic_evidence=str(self.evidence))
        self.write_decision()
        self.evidence.write_text(json.dumps(dict(source_sha256=self.source_hash,status='verified_acoustic_bounds',previous_word_end=.4,failed_audio_onset=.55,last_complete_audio_onset=1.020)), encoding="utf-8")

    def write_decision(self):
        with self.decision.open('w',newline='', encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(self.row));writer.writeheader();writer.writerow(self.row)

    def args(self):
        return argparse.Namespace(source=self.source,analysis_dir=self.analysis,output_dir=self.out,overwrite=False,fps=None,
                output_name='rough.mp4',approve_candidate=['RT001'],decision_file=self.decision,confirmed_delete=[],crf=18,preset='ultrafast')

    def test_actual_frame_boundary_crossing_onset_is_rejected(self):
        self.row["delete_end"]="1.04";self.write_decision()
        with patch.object(pipeline,'probe',return_value=self.meta),patch.object(pipeline,'run') as renderer:
            with self.assertRaisesRegex(SystemExit,'quantized.*overlaps|quantiz.*onset'):
                pipeline.rough_cut(self.args())
        renderer.assert_not_called();self.assertFalse(self.out.exists())

    def test_long_sentence_retake_also_requires_acoustic_evidence(self):
        self.row['acoustic_evidence']='';self.write_decision()
        with patch.object(pipeline,'probe',return_value=self.meta),patch.object(pipeline,'run') as renderer:
            with self.assertRaisesRegex(SystemExit,'acoustic_evidence'):
                pipeline.rough_cut(self.args())
        renderer.assert_not_called();self.assertFalse(self.out.exists())

    def test_acoustic_evidence_cannot_be_from_another_source(self):
        data=json.loads(self.evidence.read_text(encoding="utf-8"));data['source_sha256']='other';self.evidence.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(pipeline,'probe',return_value=self.meta),patch.object(pipeline,'run') as renderer:
            with self.assertRaisesRegex(SystemExit,'source-bound'):
                pipeline.rough_cut(self.args())
        renderer.assert_not_called()


if __name__=='__main__':
    unittest.main()
