"""End-to-end synthetic-media protocol tests; never real listening acceptance.

FFmpeg performs actual extraction, trimming, encoding and decoding. ASR alone
is mocked: the whole-file pass contains one 我 while a short joint window exposes
我我. All user/listening confirmations are explicitly SYNTHETIC fixtures. No
model, private footage, network, or production project is used.
"""
import array
import contextlib
import copy
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import run_pipeline as pipeline
from review_state import REQUIRED_CHECKS, full_coverage
from stage_gate import CHECKS


def write_json(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


FFMPEG=os.environ.get('XX3ZDJJ_TEST_FFMPEG') or shutil.which('ffmpeg')
FFPROBE=os.environ.get('XX3ZDJJ_TEST_FFPROBE') or shutil.which('ffprobe')
FONT=os.environ.get('XX3ZDJJ_TEST_FONT') or next((str(p) for p in [
    Path('/System/Library/Fonts/Helvetica.ttc'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/'arial.ttf',
    Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/'msyh.ttc'] if p.is_file()),None)


@unittest.skipUnless(FFMPEG and FFPROBE and FONT,'FFmpeg/FFprobe and an installed font are required')
class AnalysisToCaptionsTests(unittest.TestCase):
    def setUp(self):
        parent=os.environ.get('XX3ZDJJ_TEST_OUTPUT')
        if parent:Path(parent).mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='analysis_to_captions_',dir=parent)
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'source.mp4';wav=self.root/'fixture.wav'
        pcm=array.array('h',[0])*64000
        for a,b in ((.6,.78),(1.1,1.35),(1.45,2.8)):
            for i in range(round(a*16000),round(b*16000)):
                pcm[i]=round(8000*math.sin(2*math.pi*200*i/16000))
        with wave.open(str(wav),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(pcm.tobytes())
        subprocess.run([FFMPEG,'-y','-v','error','-f','lavfi','-i','color=s=64x96:r=24:d=4',
                        '-i',str(wav),'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(self.source)],check=True,capture_output=True)
        self.source_hash=pipeline.sha256(self.source)
        self.env=os.environ.copy();self.env.update(XX3ZDJJ_FFMPEG=FFMPEG,XX3ZDJJ_FFPROBE=FFPROBE,
                                                   PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
        self.analysis=self.root/'analysis';self.rough=self.root/'rough';self.residual=self.root/'residual'
        self.recognition_calls=[]

    def invoke_main(self, *argv):
        output=io.StringIO()
        with mock.patch.dict(os.environ,self.env),mock.patch.object(sys,'argv',[str(Path(pipeline.__file__)),*map(str,argv)]),contextlib.redirect_stdout(output):
            code=pipeline.main()
        return code,output.getvalue()

    def whole_transcript(self, source):
        # Deliberately swallowed first attempt: only one 我 in global ASR.
        words=[{'word':'我','start':1.1,'end':1.3,'probability':.99},
               {'word':'测试','start':1.45,'end':2.05,'probability':.99},
               {'word':'通过','start':2.1,'end':2.6,'probability':.99}]
        return {'source_sha256':pipeline.sha256(source),'language':'zh','language_probability':1,
                'segments':[{'start':1.1,'end':2.6,'text':'我测试通过','words':words}]}

    def mocked_cached(self, source, audio, target, args, **kwargs):
        transcript=self.whole_transcript(source)
        write_json(target,transcript);self.recognition_calls.append(('whole',str(source)))
        return transcript

    def mocked_decoder(self, decoder, window):
        self.recognition_calls.append(('window',dict(window)))
        length=float(window['end'])-float(window['start'])
        if not window.get('kind') and float(window['start'])==0 and length>=3:
            return self.whole_transcript(decoder.source)
        if window.get('kind')=='two_activity_context':
            words=[{'word':'我','start':.12,'end':.20,'probability':.99},
                   {'word':'我','start':.30,'end':.39,'probability':.99}]
        else:
            finish=min(.16,length-.001)
            words=[{'word':'我','start':min(.02,finish/2),'end':finish,'probability':.99}] if finish>0 else []
        return {'language':'zh','language_probability':1,'segments':[{'start':0,'end':length,'text':''.join(w['word'] for w in words),'words':words}]}

    def analyze(self):
        def decode(decoder, window):return self.mocked_decoder(decoder,window)
        with mock.patch.object(pipeline,'cached_recognition',side_effect=self.mocked_cached),mock.patch.object(pipeline.OpeningDecoder,'__call__',decode):
            code,text=self.invoke_main('analyze','--source',self.source,'--output-dir',self.analysis,
                                       '--retake-policy','none','--single-pass','--model','synthetic_no_model')
        self.assertEqual(code,0,text)
        return read_json(self.analysis/'review-report.json')

    def render_and_review(self, deleted=False):
        self.analyze()
        args=['rough-cut','--source',self.source,'--analysis-dir',self.analysis,'--output-dir',self.rough,'--preset','ultrafast']
        if deleted:args+=['--confirmed-delete','0.4:1.4:SYNTHETIC explicitly confirmed trim']
        code,text=self.invoke_main(*args);self.assertEqual(code,0,text)
        self.media=self.rough/'rough_cut_no_captions.mp4'
        def decode(decoder, window):return self.mocked_decoder(decoder,window)
        with mock.patch.object(pipeline.OpeningDecoder,'__call__',decode):
            code,text=self.invoke_main('residual-check','--source',self.media,'--output-dir',self.residual,'--model','synthetic_no_model')
        self.assertEqual(code,0,text)
        self.review=read_json(self.residual/'review-report.json')
        self.assertEqual(pipeline.sha256(self.source),self.source_hash)
        return self.review

    def protocol_evidence(self, resolve=True):
        evidence=self.root/'synthetic_listening.txt'
        evidence.write_text('SYNTHETIC PROTOCOL FIXTURE ONLY: not a real user, no person listened to tones.\n模拟确认仅验证闸门，不能用于真实视频。',encoding='utf-8')
        reviewer={'kind':'user','method':'user_listening','quote':'SYNTHETIC fixture listening statement, not real listening','recorded_at':'synthetic_fixture_timestamp'}
        resolutions={'schema_version':2,'source_sha256':pipeline.sha256(self.media),
                     'report_sha256':pipeline.sha256(self.residual/'review-report.json'),
                     'alerts':[{'alert_id':a['id'],'decision':'retain','verification':'confirmed_benign',
                                'coverage':{'scope':'alert_window','start':a['start'],'end':a['end']},
                                'assessment':'SYNTHETIC tone/ASR fixture explicitly assessed, not real speech',
                                'reviewer':reviewer} for a in self.review['alerts']],
                     'check_resolutions':[{'check_id':key,'verification':'confirmed','coverage':full_coverage(self.review['duration_seconds']),
                                           'assessment':'SYNTHETIC full media protocol supplement; not actual listening',
                                           'reviewer':reviewer} for key in REQUIRED_CHECKS]}
        for item in resolutions['alerts']+resolutions['check_resolutions']:
            item['evidence']=self.resolution_evidence(item,kind='listening_confirmation')
        self.resolutions=self.root/'resolutions.json';write_json(self.resolutions,resolutions)
        gate={'stage':'rough-cut','artifacts':{'source':{'sha256':pipeline.sha256(self.media)}},
              'checks':{key:{'status':'passed','method':'SYNTHETIC protocol fixture only','evidence':[str(evidence)]} for key in CHECKS['rough-cut']},
              'blocking_counts':{'approved_not_executed':0,'known_unfixed':0,'unresolved':0},
              'user_approval':{'status':'approved','message':'SYNTHETIC user preview approval; not a real user','recorded_at':'synthetic_fixture_timestamp','evidence':str(evidence)},
              'residual_review':{'report':{'path':str(self.residual/'review-report.json'),'sha256':pipeline.sha256(self.residual/'review-report.json')}}}
        if resolve:gate['residual_review']['resolutions']={'path':str(self.resolutions),'sha256':pipeline.sha256(self.resolutions)}
        self.gate=self.root/'approval.json';write_json(self.gate,gate)
        self.script=self.root/'script.txt';self.script.write_text('我测试通过\n',encoding='utf-8')
        self.caption_transcript=self.root/'caption_transcript.json';write_json(self.caption_transcript,self.whole_transcript(self.media))
        return gate,resolutions,evidence

    def resolution_evidence(self,item,kind='machine_verification'):
        """Scoped synthetic observations, never a claim that real audio was heard."""
        key='alert_id' if 'alert_id' in item else 'check_id'
        target=item[key];coverage=copy.deepcopy(item['coverage'])
        path=self.root/('synthetic_'+kind+'_'+target+'.json')
        write_json(path,{'schema_version':2,'kind':kind,
            'source_sha256':pipeline.sha256(self.media),'report_sha256':pipeline.sha256(self.residual/'review-report.json'),
            key:target,'coverage':coverage,'verification':item['verification'],
            'observations':[{'method':'SYNTHETIC tone/ASR fixture timing and edit-map comparison',
                'finding':f'SYNTHETIC fixture only: target {target} covers {coverage["start"]:.6f}-{coverage["end"]:.6f}s in the generated media; fixture mapping and word records support {item["verification"]}. No real speech or listening acceptance.'}]})
        return [{'kind':kind,'path':str(path),'sha256':pipeline.sha256(path)}]

    def captions_cli(self, suffix='captions'):
        out=self.root/suffix
        command=[sys.executable,str(Path(pipeline.__file__)),'captions','--source',str(self.media),
                 '--script',str(self.script),'--transcript',str(self.caption_transcript),'--output-dir',str(out),
                 '--approval-report',str(self.gate),'--font-name','Helvetica','--font-file',FONT,'--font-size','30']
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',env=self.env)
        return result,out

    def test_none_still_detects_local_restart_hidden_by_whole_asr(self):
        report=self.analyze()
        self.assertEqual(''.join(w['word'] for w in pipeline.flatten_words(read_json(self.analysis/'transcript.json'))).count('我'),1)
        self.assertTrue(any(a.get('text')=='我' and a.get('kind','').startswith('opening_overlap') for a in report['alerts']))
        self.assertNotEqual(report['quality_status'],'passed')
        summary=read_json(self.analysis/'analysis-summary.json')
        self.assertEqual(summary['retake_policy'],'none')
        self.assertEqual(summary['detection_checks']['opening_overlap']['status'],'executed')
        self.assertTrue(any(k=='window' for k,x in self.recognition_calls))

    def test_retained_source_alerts_survive_actual_edit_mapping(self):
        report=self.render_and_review()
        original=read_json(self.analysis/'review-report.json')
        self.assertEqual(report['source_review_lineage']['status'],'executed')
        for alert in original['alerts']:
            carried=[x for x in report['alerts'] if x.get('upstream_alert_id')==alert['id']]
            self.assertTrue(carried,alert['id'])
            self.assertTrue(all(x['review_required'] for x in carried))
            self.assertAlmostEqual(carried[0]['start'],alert['start'],places=5)
            self.assertAlmostEqual(carried[0]['end'],alert['end'],places=5)

    def test_deleted_warning_becomes_exact_boundary_recheck_not_fixed(self):
        report=self.render_and_review(deleted=True)
        mapping=read_json(self.rough/'edit-map.json');original=read_json(self.analysis/'review-report.json')
        removed=[a for a in original['alerts'] if .4<a['start']<a['end']<1.4]
        self.assertTrue(removed,'synthetic opening alert must lie entirely in the removed interval')
        for alert in removed:
            carried=[x for x in report['alerts'] if x.get('upstream_alert_id')==alert['id']]
            self.assertTrue(carried)
            after=next(s for s in mapping['kept_segments'] if s['source_start']>=alert['end'])
            expected=(max(0,after['output_start']-.3),min(report['duration_seconds'],after['output_start']+.5))
            self.assertAlmostEqual(carried[0]['start'],expected[0],places=5)
            self.assertAlmostEqual(carried[0]['end'],expected[1],places=5)
            self.assertTrue(carried[0]['review_required'])

    def test_zero_counts_without_resolutions_blocks_actual_caption_entry(self):
        self.render_and_review();self.protocol_evidence(resolve=False)
        result,out=self.captions_cli()
        self.assertEqual(result.returncode,2,result.stderr+result.stdout)
        self.assertIn('unresolved',result.stdout)
        self.assertFalse((out/'captions.srt').exists())

    def test_missing_evidence_blocks_actual_caption_entry(self):
        self.render_and_review();gate,resolutions,evidence=self.protocol_evidence()
        for item in resolutions['alerts']+resolutions['check_resolutions']:item['evidence']=[]
        write_json(self.resolutions,resolutions)
        gate['residual_review']['resolutions']['sha256']=pipeline.sha256(self.resolutions);write_json(self.gate,gate)
        result,out=self.captions_cli();self.assertEqual(result.returncode,2,result.stderr+result.stdout)
        self.assertIn('evidence',result.stdout);self.assertFalse(out.exists())

    def test_stale_report_hash_blocks_actual_caption_entry(self):
        self.render_and_review();gate,resolutions,evidence=self.protocol_evidence()
        review=read_json(self.residual/'review-report.json');review['test_revision']='SYNTHETIC modified review version'
        write_json(self.residual/'review-report.json',review)
        result,out=self.captions_cli();self.assertEqual(result.returncode,2,result.stderr+result.stdout)
        self.assertIn('changed',result.stdout);self.assertFalse(out.exists())

    def test_missing_user_confirmation_blocks_actual_caption_entry(self):
        self.render_and_review();gate,resolutions,evidence=self.protocol_evidence()
        gate['user_approval']['status']='pending';write_json(self.gate,gate)
        result,out=self.captions_cli();self.assertEqual(result.returncode,2,result.stderr+result.stdout)
        self.assertIn('approved',result.stdout);self.assertFalse(out.exists())

    def test_stale_media_hash_blocks_actual_caption_entry(self):
        self.render_and_review();self.protocol_evidence()
        with self.media.open('ab') as stream:stream.write(b'SYNTHETIC new-media-version marker')
        result,out=self.captions_cli();self.assertEqual(result.returncode,2,result.stderr+result.stdout)
        self.assertIn('version',result.stdout);self.assertFalse(out.exists())
        self.assertEqual(pipeline.sha256(self.source),self.source_hash)

    def test_missing_source_lineage_blocks_even_with_synthetic_resolutions(self):
        self.render_and_review();gate,resolutions,evidence=self.protocol_evidence()
        review=read_json(self.residual/'review-report.json');review.pop('source_review_lineage')
        write_json(self.residual/'review-report.json',review)
        digest=pipeline.sha256(self.residual/'review-report.json')
        resolutions['report_sha256']=digest;write_json(self.resolutions,resolutions)
        gate['residual_review']['report']['sha256']=digest
        gate['residual_review']['resolutions']['sha256']=pipeline.sha256(self.resolutions)
        write_json(self.gate,gate)
        result,out=self.captions_cli();self.assertEqual(result.returncode,2,result.stderr+result.stdout)
        self.assertIn('lineage unavailable',result.stdout);self.assertFalse(out.exists())

    def test_zero_duration_or_explicitly_unverified_word_blocks_after_valid_gate(self):
        self.render_and_review();self.protocol_evidence()
        original=read_json(self.caption_transcript)
        for mode in ('zero_duration','explicit_timing_unverified'):
            with self.subTest(mode=mode):
                transcript=copy.deepcopy(original);word=transcript['segments'][0]['words'][0]
                if mode=='zero_duration':word['end']=word['start']
                else:word['timing_status']='timing_unverified'
                write_json(self.caption_transcript,transcript)
                result,out=self.captions_cli('captions_'+mode)
                self.assertEqual(result.returncode,2,result.stderr+result.stdout)
                self.assertFalse((out/'captions.srt').exists())
                validation=read_json(out/'caption-validation.json')
                self.assertTrue(validation['timing_unverified'])
                self.assertEqual(validation['invalid_word_ranges'],[0])
                self.assertFalse(validation['timing_unverified'][0]['usable_for_subtitle_timing'])

    def test_complete_real_media_lineage_and_synthetic_confirmations_export_srt(self):
        self.render_and_review();self.protocol_evidence()
        result,out=self.captions_cli();self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        text=(out/'captions.srt').read_text(encoding='utf-8-sig')
        self.assertIn('我测试通过',text)
        self.assertTrue((out/'captions.ass').is_file())
        self.assertEqual(pipeline.sha256(self.source),self.source_hash)
        validation=read_json(out/'caption-validation.json')
        self.assertEqual(validation['alignment_character_coverage'],1)
        self.assertEqual(validation['overlaps'],0)
        self.assertEqual(validation['human_listening'],'not performed')

    def test_semiauto_machine_review_without_listening_can_enter_captions(self):
        self.render_and_review();gate,resolutions,_=self.protocol_evidence()
        evidence=self.root/'synthetic_machine_review.txt'
        evidence.write_text('SYNTHETIC machine-only review fixture: timing, coverage, mapping; no listening.',encoding='utf-8')
        for item in resolutions['alerts']+resolutions['check_resolutions']:
            item['reviewer']={'kind':'agent','method':'machine_evidence_review',
                'recorded_at':'synthetic','quote':'Synthetic timing, coverage and source mapping reviewed.'}
            item['assessment']='Synthetic machine evidence covers this item; no listening claim.'
            item['evidence']=self.resolution_evidence(item)
        write_json(self.resolutions,resolutions)
        gate['residual_review']['resolutions']['sha256']=pipeline.sha256(self.resolutions)
        # Semi-auto still needs the stage approval, but that approval is not listening proof.
        approval=self.root/'synthetic_stage_approval.txt'
        approval.write_text('SYNTHETIC user approved this preview version; no listening statement.',encoding='utf-8')
        gate['user_approval']['evidence']=str(approval)
        write_json(self.gate,gate)
        result,out=self.captions_cli('machine_only_captions')
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertTrue((out/'captions.srt').is_file())


if __name__=='__main__':unittest.main()
