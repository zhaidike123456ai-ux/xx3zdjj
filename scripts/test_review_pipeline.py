"""Review orchestration regressions with deterministic ASR, never a listening claim."""
import argparse
import io
import json
import tempfile
import unittest
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

    def decode(self,window):
        self.calls.append(window)
        return {'segments':[{'start':.1,'end':.5,'text':'我发现','words':[
            {'word':'我','start':.1,'end':.25,'probability':.99},
            {'word':'发现','start':.25,'end':.5,'probability':.99}]}]}

    def opening(self,source,audio,out,args,words,decoder=None):
        value={'status':'executed','reason':'synthetic opening check','coverage':{'complete':True},'alerts':[],'windows':[]}
        (out/'opening-review.json').write_text(json.dumps(value))
        return value

    def run_stage(self,**overrides):
        for k,v in overrides.items():setattr(self.args,k,v)
        with patch.object(pipeline,'probe',return_value={'format':{'duration':'5'}}), \
             patch.object(pipeline,'extract_audio'),patch.object(pipeline,'OpeningDecoder',return_value=self.decode), \
             patch.object(pipeline,'opening_audit',side_effect=self.opening) as opening, \
             patch.object(pipeline,'run',return_value=SimpleNamespace(stderr='',stdout='')), \
             patch.object(pipeline,'propagate_analysis_alerts',return_value=([],{'status':'unavailable','reason':'synthetic no lineage'})), \
             redirect_stdout(io.StringIO()):
            result=pipeline.review_stage(self.args)
        return result,json.loads((self.output/'review-report.json').read_text()),opening

    def test_no_asr_candidates_is_unverified_not_quality_passed(self):
        result,report,opening=self.run_stage()
        self.assertEqual(result,0)
        self.assertEqual(report['command_status'],'completed')
        self.assertEqual(report['quality_status'],'unverified')
        self.assertEqual(report['alerts'],[])
        self.assertEqual(report['checks']['word_integrity']['status'],'unavailable')
        opening.assert_called_once()
        self.assertEqual(opening.call_args.args[4][0]['word'],'我')

    def test_user_window_adds_overlap_and_stays_local_not_full_coverage(self):
        _,report,_=self.run_stage(stage='local-review',window=['2:2.6'])
        self.assertIn({'start':2.,'end':2.6},self.calls)
        self.assertTrue(any(x['start']<2 and x['end']>2.6 for x in self.calls))
        self.assertEqual(report['stage'],'local-review')
        self.assertNotEqual(report['checks']['repeated_speech']['coverage']['scope'],'full_media')

    def test_feedback_cannot_be_closed_without_original_reference(self):
        with self.assertRaisesRegex(SystemExit,'reference-source'):
            self.run_stage(stage='local-review',window=['2:2.6'],feedback='开头重复')
        self.assertFalse((self.output/'review-report.json').exists())

    def test_feedback_writes_original_and_current_evidence_and_alert(self):
        original=self.root/'original.mp4'; original.write_bytes(b'synthetic original')
        _,report,_=self.run_stage(stage='local-review',window=['2:2.6'],feedback='开头重复',
            reference_source=original,reference_window=['1:1.6'])
        other=json.loads(Path(report['reference_review']['path']).read_text())
        self.assertEqual(other['source_sha256'],pipeline.sha256(original))
        self.assertEqual(report['source_sha256'],pipeline.sha256(self.source))
        self.assertTrue(any(x['kind']=='user_feedback' and x['review_required'] for x in report['alerts']))

    def test_failed_full_decode_does_not_claim_full_detection(self):
        self.decode=lambda _: (_ for _ in ()).throw(RuntimeError('synthetic decoder failure'))
        _,report,_=self.run_stage()
        self.assertEqual(report['windows'][0]['status'],'unavailable')
        self.assertEqual(report['checks']['repeated_speech']['status'],'unavailable')
        self.assertEqual(report['quality_status'],'unverified')


if __name__=='__main__': unittest.main()
