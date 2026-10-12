"""Review orchestration regressions with deterministic ASR, never a listening claim."""
import argparse
import io
import json
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_pipeline as pipeline


class ReviewPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'current.mp4'; self.source.write_bytes(b'synthetic')
        self.output=self.root/'review'
        self.args=argparse.Namespace(source=self.source,output_dir=self.output,stage='residual-check',
            model='not-loaded',cpu_threads=1,window=[],candidates=None,feedback=None,reference_source=None,reference_window=[])
        self.calls=[]
        self.lineage={'status':'unavailable','reason':'synthetic no lineage'}

    def decode(self,window):
        self.calls.append(window)
        return {'segments':[{'start':.1,'end':.5,'text':'我发现','words':[
            {'word':'我','start':.1,'end':.25,'probability':.99},
            {'word':'发现','start':.25,'end':.5,'probability':.99}]}]}

    def extract(self,source,audio):
        with wave.open(str(audio),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000)
            stream.writeframes(b'\0\0'*80000)

    def opening(self,source,audio,out,args,words,decoder=None):
        value={'status':'executed','reason':'synthetic opening check','coverage':{'complete':True},'alerts':[],'windows':[]}
        (out/'opening-review.json').write_text(json.dumps(value), encoding="utf-8")
        return value

    def run_stage(self,**overrides):
        for k,v in overrides.items():setattr(self.args,k,v)
        with patch.object(pipeline,'probe',return_value={'format':{'duration':'5'}}), \
             patch.object(pipeline,'extract_audio',side_effect=self.extract),patch.object(pipeline,'OpeningDecoder',return_value=self.decode), \
             patch.object(pipeline,'opening_audit',side_effect=self.opening) as opening, \
             patch.object(pipeline,'run',return_value=SimpleNamespace(stderr='',stdout='')), \
             patch.object(pipeline,'propagate_analysis_alerts',return_value=([],self.lineage)), \
             redirect_stdout(io.StringIO()):
            result=pipeline.review_stage(self.args)
        return result,json.loads((self.output/'review-report.json').read_text(encoding="utf-8")),opening

    def test_no_asr_candidates_is_unverified_not_quality_passed(self):
        result,report,opening=self.run_stage()
        self.assertEqual(result,0)
        self.assertEqual(report['command_status'],'completed')
        self.assertEqual(report['quality_status'],'unverified')
        self.assertEqual(report['alerts'],[])
        self.assertEqual(report['checks']['word_integrity']['status'],'unavailable')
        self.assertIn('source-to-output boundary mapping unavailable',report['checks']['word_integrity']['reason'])
        opening.assert_called_once()
        self.assertEqual(opening.call_args.args[4][0]['word'],'我')

    def test_machine_timing_execution_does_not_require_hearing_or_claim_quality_pass(self):
        self.lineage={'status':'executed','reason':'synthetic verified mapping'}
        _,report,_=self.run_stage()
        check=report['checks']['word_integrity']
        self.assertEqual(check['status'],'executed')
        self.assertEqual(check['result'],'unverified')
        self.assertEqual(check['machine_scope']['usable_words'],2)
        self.assertEqual(check['machine_scope']['completed_timing_windows'],1)
        self.assertEqual(check['machine_scope']['source_mapping_status'],'executed')
        self.assertIs(check['optional_listening']['required'],False)
        self.assertEqual(check['optional_listening']['status'],'not_performed')
        self.assertEqual(report['quality_status'],'unverified')
        self.assertEqual(report['semantic_completeness'],'not verified')

    def test_empty_asr_is_not_usable_word_integrity_evidence(self):
        self.lineage={'status':'executed'}
        self.decode=lambda _: {'segments':[]}
        _,report,_=self.run_stage()
        check=report['checks']['word_integrity']
        self.assertEqual(check['status'],'unavailable')
        self.assertEqual(check['machine_scope']['usable_words'],0)
        self.assertIn('no usable word timing evidence',check['reason'])
        self.assertEqual(report['quality_status'],'unverified')

    def test_user_window_adds_overlap_and_stays_local_not_full_coverage(self):
        _,report,_=self.run_stage(stage='local-review',window=['2:2.6'])
        self.assertIn({'start':2.,'end':2.6},self.calls)
        self.assertTrue(any(x['start']<2 and x['end']>2.6 for x in self.calls))
        self.assertEqual(report['stage'],'local-review')
        self.assertNotEqual(report['checks']['repeated_speech']['coverage']['scope'],'full_media')
        self.assertEqual(report['checks']['word_integrity']['status'],'executed')
        self.assertEqual(report['checks']['word_integrity']['coverage']['scope'],'local_windows')

    def test_feedback_cannot_be_closed_without_original_reference(self):
        with self.assertRaisesRegex(SystemExit,'reference-source'):
            self.run_stage(stage='local-review',window=['2:2.6'],feedback='开头重复')
        self.assertFalse((self.output/'review-report.json').exists())

    def test_feedback_writes_original_and_current_evidence_and_alert(self):
        original=self.root/'original.mp4'; original.write_bytes(b'synthetic original')
        _,report,_=self.run_stage(stage='local-review',window=['2:2.6'],feedback='开头重复',
            reference_source=original,reference_window=['1:1.6'])
        other=json.loads(Path(report['reference_review']['path']).read_text(encoding="utf-8"))
        self.assertEqual(other['source_sha256'],pipeline.sha256(original))
        self.assertEqual(report['source_sha256'],pipeline.sha256(self.source))
        self.assertTrue(any(x['kind']=='user_feedback' and x['review_required'] for x in report['alerts']))

    def test_zero_duration_word_preserves_nine_normal_words_and_raw_output(self):
        self.lineage={'status':'executed'}
        words=[{'word':char,'start':i*.2,'end':i*.2+.15} for i,char in enumerate('不知道这个玩法图片')]
        self.assertEqual(len(words),9)
        words.append({'word':'上','start':2.48,'end':2.48})
        self.decode=lambda _: {'segments':[{'start':0,'end':2.48,'text':'不知道这个玩法图片上','words':words}]}
        _,report,_=self.run_stage()
        window=report['windows'][0]
        self.assertEqual(len(window['words']),9)
        self.assertEqual(len(window['raw_output']['segments'][0]['words']),10)
        issue=window['timing_unverified'][0]
        self.assertEqual((issue['word'],issue['index'],issue['local_start'],issue['local_end']),('上',9,2.48,2.48))
        self.assertEqual(issue['timing_status'],'timing_unverified')
        self.assertFalse(issue['usable_for_subtitle_timing'])
        self.assertEqual(window['status'],'unavailable')
        self.assertEqual(report['quality_status'],'review_required')
        check=report['checks']['word_integrity']
        self.assertEqual(check['status'],'unavailable')
        self.assertEqual(check['result'],'review_required')
        self.assertEqual(check['machine_scope']['timing_unverified_words'],1)
        warning=next(x for x in report['alerts'] if x.get('evidence',{}).get('timing_status')=='timing_unverified')
        self.assertEqual((warning['start'],warning['end']),(0.,5.))
        self.assertEqual(warning['scope_type'],'review_window_not_word_boundary')

    def test_padding_is_clamped_in_public_residual_path_and_raw_measurement_survives(self):
        def padded(source,audio):
            with wave.open(str(audio),'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000)
                stream.writeframes(b'\0\0'*int(24.064*16000))
        self.args.stage='residual-check'
        log='silence_start: 23.613437\nsilence_end: 24.064 | silence_duration: 0.450563'
        with patch.object(pipeline,'probe',return_value={'format':{'duration':'24.05'}}), \
             patch.object(pipeline,'extract_audio',side_effect=padded),patch.object(pipeline,'OpeningDecoder',return_value=self.decode), \
             patch.object(pipeline,'opening_audit',side_effect=self.opening), \
             patch.object(pipeline,'run',return_value=SimpleNamespace(stderr=log,stdout='')), \
             patch.object(pipeline,'propagate_analysis_alerts',return_value=([],{'status':'unavailable','reason':'synthetic no lineage'})),redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.review_stage(self.args),0)
        report=json.loads((self.output/'review-report.json').read_text(encoding='utf-8'))
        pause=next(x for x in report['alerts'] if x['kind']=='pause_review')
        self.assertEqual((pause['start'],pause['end']),(23.613437,24.05))
        self.assertTrue(pause['review_required'])
        self.assertTrue(all(0<=x['start']<x['end']<=24.05 for x in report['alerts']))
        audit=json.loads((self.output/'silence-measurements.json').read_text(encoding='utf-8'))
        raw=audit['passes']['residual']['measurements'][0]
        self.assertEqual(raw['raw_end'],24.064)
        self.assertAlmostEqual(raw['end_adjustment_seconds'],-.014)
        self.assertEqual(audit['duration_comparison']['status'],'within_tolerance')

    def test_failed_full_decode_does_not_claim_full_detection(self):
        self.decode=lambda _: (_ for _ in ()).throw(RuntimeError('synthetic decoder failure'))
        _,report,_=self.run_stage()
        self.assertEqual(report['windows'][0]['status'],'unavailable')
        self.assertEqual(report['checks']['repeated_speech']['status'],'unavailable')
        self.assertEqual(report['checks']['word_integrity']['status'],'unavailable')
        self.assertIn('ASR windows failed',report['checks']['word_integrity']['reason'])
        self.assertEqual(report['quality_status'],'unverified')


if __name__=='__main__': unittest.main()
