"""Opt-in regression for an already labelled short repeated-opening sample.

This is NOT an accuracy test for arbitrary normal talking-head footage. Only
set XX3ZDJJ_REAL_RESTART_SOURCE after confirming that the sample contains a
repeated opening token. No private fixture is distributed in this repository.

Required: XX3ZDJJ_REAL_RESTART_SOURCE, XX3ZDJJ_REAL_RESTART_TRANSCRIPT (cached
source-bound full transcript), XX3ZDJJ_REAL_RESTART_MODEL (existing local model).
Optional: XX3ZDJJ_REAL_RESTART_EXPECTED_TOKEN (default 我),
XX3ZDJJ_REAL_RESTART_OUTPUT (external audit/cache directory). With no SOURCE the
test skips. Supplied but incomplete/mismatched fixture configuration fails.
Only planned opening windows run; one decoder/model is shared. No automatic cut.
Timing-only anomalies may leave a window incomplete, but must retain the raw
transcript, its valid words and an explicit review alert. Real decoder exceptions
still fail this regression. This does not waive listening or the quality gate.
"""
import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path

from opening_review import execute_opening_review, source_relative_word_evidence
from run_pipeline import (OpeningDecoder, clean_token, extract_audio, flatten_words,
                          opening_audit, sha256)


class RealOpeningRegression(unittest.TestCase):
    def test_labelled_repeated_opening_is_reviewed_not_silently_passed(self):
        supplied=os.environ.get('XX3ZDJJ_REAL_RESTART_SOURCE')
        if not supplied:
            self.skipTest('opt-in labelled private sample not supplied; no speech test executed')
        source=Path(supplied).expanduser().resolve()
        transcript_value=os.environ.get('XX3ZDJJ_REAL_RESTART_TRANSCRIPT')
        model_value=os.environ.get('XX3ZDJJ_REAL_RESTART_MODEL')
        self.assertTrue(transcript_value,'supply cached source-bound transcript for this labelled sample')
        self.assertTrue(model_value,'supply an existing local model; this test never downloads one')
        transcript=Path(transcript_value).expanduser().resolve()
        model=Path(model_value).expanduser().resolve()
        self.assertTrue(source.is_file());self.assertTrue(transcript.is_file());self.assertTrue(model.is_dir())
        source_before=sha256(source)
        cached=json.loads(transcript.read_text(encoding='utf-8-sig'))
        self.assertEqual(cached.get('source_sha256'),source_before,'transcript source hash must match, not just its filename')
        words=flatten_words(cached)
        self.assertTrue(words,'the labelled fixture needs existing source word times')
        token=clean_token(os.environ.get('XX3ZDJJ_REAL_RESTART_EXPECTED_TOKEN','我'))
        self.assertTrue(token)
        output=os.environ.get('XX3ZDJJ_REAL_RESTART_OUTPUT')
        if output:
            out=Path(output).expanduser().resolve()
            repository=Path(__file__).resolve().parents[1]
            self.assertFalse(out==repository or repository in out.parents,'private evidence must remain outside repository')
            out.mkdir(parents=True,exist_ok=True)
        else:
            folder=tempfile.TemporaryDirectory(prefix='xx3zdjj_real_opening_')
            self.addCleanup(folder.cleanup);out=Path(folder.name)
        args=argparse.Namespace(model=str(model),cpu_threads=4)
        audio=out/'source_16k_mono.wav'
        extract_audio(source,audio)
        decoder=OpeningDecoder(source,out/'opening_windows',args)
        report=opening_audit(source,audio,out,args,words,decoder=decoder)
        self.assertIn(report['status'],('executed','unavailable'),report.get('reason'))
        self.assertTrue(report['coverage']['complete'])
        self.assertLessEqual(len(report['windows']),10)
        self.assertEqual(report['scheduled_windows'],len(report['windows']))
        completed=[w for w in report['windows'] if w['status']=='executed']
        failed=[w for w in report['windows'] if w['status']!='executed']
        self.assertEqual(report['completed_windows'],len(completed))
        self.assertEqual(report['failed_windows'],len(failed))
        self.assertEqual(report['temporal_coverage_complete'],report['coverage']['complete'])
        self.assertEqual(report['multiscale_complete'],not failed)
        self.assertNotEqual(report['quality_status'],'passed')
        self.assertEqual(report['status'],'unavailable' if failed else 'executed')
        timing_alerts=[a for a in report['alerts'] if a.get('check_id')=='word_integrity'
                       and a.get('evidence',{}).get('timing_status')=='timing_unverified']
        for row in failed:
            self.assertFalse(row.get('error_type'),
                             'real decoder exceptions must not be accepted as timing-only anomalies: '+repr(row))
            self.assertTrue(row.get('timing_unverified'),
                            'an unavailable window must explain specific timing evidence: '+repr(row))
            self.assertIsInstance(row.get('raw_output'),dict,'preserve the actual decoder transcript')
            self.assertEqual(len(row['raw_words']),len(row['words'])+len(row['timing_unverified']))
            self.assertEqual(row['quality_status'],'review_required')
            for issue in row['timing_unverified']:
                self.assertEqual(issue['timing_status'],'timing_unverified')
                self.assertFalse(issue['usable_for_cut']);self.assertFalse(issue['usable_for_subtitle_timing'])
                self.assertEqual(issue['raw_word'],row['raw_words'][issue['index']])
                self.assertTrue(any(a['review_required'] is True
                                    and a['evidence'].get('window_id')==issue['window_id']
                                    and a['evidence'].get('index')==issue['index'] for a in timing_alerts),
                                'each incomplete word must retain an explicit review alert')
        if failed:self.assertEqual(report['quality_status'],'review_required')
        self.assertLessEqual(report['retried_windows'],1)
        for retry in report['retry_windows']:
            self.assertFalse(retry.get('error_type'),'real retry decoder exceptions must also remain failures')
        by_kind={}
        for window in report['windows']:by_kind.setdefault(window.get('kind'),[]).append(window)
        for kind in ('isolated_first_activity','second_activity_context','two_activity_context','overlapping_context'):
            self.assertTrue(by_kind.get(kind),'missing multiscale evidence: '+kind)
        isolated=by_kind['isolated_first_activity'][0]
        later=by_kind['second_activity_context'][0]
        self.assertGreater(later['start'],isolated['start'])
        self.assertTrue(isolated.get('words'),'isolated recognition unavailable/empty must not masquerade as token confirmation')
        self.assertTrue(later.get('words'),'later context recognition unavailable/empty')
        combined=[''.join(clean_token(w['word']) for w in row.get('words',[])) for row in by_kind['two_activity_context']]
        self.assertTrue(any(token+token in text for text in combined),
                        'labelled repeated token not exposed by joint short window: '+repr(combined))
        self.assertTrue(any(clean_token(a.get('text',''))==token and a.get('review_required') is True for a in report['alerts']),
                        'must emit an actual repeated-token review candidate')
        self.assertFalse(report.get('deletion_authorized',False))
        self.assertEqual(report.get('human_listening'),'not performed')
        missing=execute_opening_review(report['plan'],asr_callback=None)
        self.assertEqual(missing['status'],'unavailable')
        self.assertEqual(missing['coverage']['fraction'],0)
        self.assertEqual(sha256(source),source_before,'source media must remain unchanged')
        evidence={'fixture_scope':'already labelled repeated-opening sample only, not arbitrary normal speech',
                  'source_sha256':source_before,'expected_token':token,'status':report['status'],
                  'coverage':report['coverage'],'candidate_count':len(report['alerts']),
                  'scheduled_windows':report['scheduled_windows'],'completed_windows':report['completed_windows'],
                  'failed_windows':report['failed_windows'],'temporal_coverage_complete':report['temporal_coverage_complete'],
                  'multiscale_complete':report['multiscale_complete'],'quality_status':report['quality_status'],
                  'timing_unverified_count':sum(len(w.get('timing_unverified',[])) for w in report['windows']),
                  'retried_windows':report['retried_windows'],
                  'isolated_text':[''.join(w['word'] for w in x.get('words',[])) for x in by_kind['isolated_first_activity']],
                  'joint_context_text':combined,'no_callback_status':missing['status'],
                  'source_unchanged':True,'media_edited':False,'human_listening':'not performed'}
        (out/'real_opening_regression.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')

    def test_labelled_zero_duration_word_keeps_other_real_words(self):
        supplied=os.environ.get('XX3ZDJJ_REAL_RESTART_SOURCE')
        window_text=os.environ.get('XX3ZDJJ_REAL_TIMING_WINDOW')
        if not supplied or not window_text:
            self.skipTest('opt-in labelled real timing-anomaly window not supplied')
        source=Path(supplied).expanduser().resolve()
        model=Path(os.environ['XX3ZDJJ_REAL_RESTART_MODEL']).expanduser().resolve()
        start,end=map(float,window_text.split(':'))
        expected=os.environ.get('XX3ZDJJ_REAL_TIMING_WORD','上')
        output=os.environ.get('XX3ZDJJ_REAL_RESTART_OUTPUT')
        if output:
            out=Path(output).expanduser().resolve()
            repository=Path(__file__).resolve().parents[1]
            self.assertFalse(out==repository or repository in out.parents)
            out.mkdir(parents=True,exist_ok=True)
        else:
            temp=tempfile.TemporaryDirectory(prefix='xx3zdjj_real_timing_')
            self.addCleanup(temp.cleanup);out=Path(temp.name)
        before=sha256(source)
        decoder=OpeningDecoder(source,out/'opening_windows',argparse.Namespace(model=str(model),cpu_threads=4))
        raw=decoder({'start':start,'end':end})
        raw_words=[w for segment in raw['segments'] for w in segment.get('words',[])]
        evidence=source_relative_word_evidence(raw_words,start,window_end=end,window_id='labelled_real_timing')
        self.assertTrue(evidence['words'],'normal recognized word evidence must remain')
        self.assertEqual(len(evidence['words'])+len(evidence['timing_unverified']),len(raw_words))
        issue=next((x for x in evidence['timing_unverified'] if x['word']==expected),None)
        self.assertIsNotNone(issue,'labelled zero-duration token not reproduced by this platform/model run')
        self.assertEqual(issue['local_start'],issue['local_end'])
        self.assertFalse(issue['usable_for_cut']);self.assertFalse(issue['usable_for_subtitle_timing'])
        self.assertEqual(evidence['raw_words'],raw_words)
        self.assertEqual(evidence['status'],'unavailable')
        self.assertEqual(evidence['quality_status'],'review_required')
        self.assertEqual(sha256(source),before)
        (out/'real_timing_regression.json').write_text(json.dumps(
            {'window':[start,end],'source_sha256':before,'raw_output':raw,**evidence,
             'source_unchanged':True,'media_edited':False,'human_listening':'not performed'},
            ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':unittest.main()
