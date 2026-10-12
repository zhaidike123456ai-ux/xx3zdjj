"""Synthetic protocol tests only; no claim of actual speech/listening acceptance."""
import json
import tempfile
import unittest
from pathlib import Path
from review_state import REQUIRED_CHECKS, file_hash, full_coverage, make_report, stable_alert_id, validate_review


def synthetic_lineage(root, source, duration):
    """Protocol-only fixture, deliberately not proof of an actual media edit."""
    root = Path(root)
    original = root / 'synthetic-original.bin'
    original.write_bytes(b'synthetic original source fixture; not actual media')
    upstream = make_report(original, duration, {
        k: {'status': 'executed', 'result': 'passed', 'method': 'synthetic detector fixture', 'coverage': full_coverage(duration)}
        for k in REQUIRED_CHECKS}, [])
    upstream['stage'] = 'analyze'
    path = root / 'source-analysis-review.json'
    path.write_text(json.dumps(upstream), encoding='utf-8')
    reference = {'path': str(path), 'sha256': file_hash(path), 'source_sha256': file_hash(original)}
    mapping = root / 'edit-map.json'
    mapping.write_text(json.dumps({'source_sha256': file_hash(original), 'output_sha256': file_hash(source),
                                  'analysis_review': reference, 'kept_segments': [
                                      {'source_start': 0, 'source_end': duration, 'output_start': 0, 'output_end': duration}]}), encoding="utf-8")
    return {'status': 'executed', 'edit_map': {'path': str(mapping), 'sha256': file_hash(mapping)}, 'report': reference}


class ReviewStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'current.mp4'
        self.source.write_bytes(b'synthetic source fixture; not real media')
        self.report_path = self.root / 'residual.json'
        self.resolutions_path = self.root / 'resolutions.json'
        self.confirmation = self.root / 'listening.txt'
        self.confirmation.write_text('SYNTHETIC protocol fixture only: normal emphasis repetition can be retained.', encoding="utf-8")
        self.report = make_report(self.source, 2.0, {
            k: {'status': 'executed', 'result': 'passed', 'method': 'synthetic detector fixture', 'coverage': full_coverage(2.0)}
            for k in REQUIRED_CHECKS
        }, [])
        self.report['source_review_lineage'] = synthetic_lineage(self.root, self.source, 2.0)
        self.resolutions = None

    def save(self):
        self.report_path.write_text(json.dumps(self.report), encoding='utf-8')
        if self.resolutions is not None:
            self.resolutions_path.write_text(json.dumps(self.resolutions), encoding='utf-8')
        return self.report_path

    def check(self):
        self.save()
        return validate_review(self.report_path, self.source, self.resolutions_path if self.resolutions is not None else None)

    def alert(self):
        alert = {'id': stable_alert_id(file_hash(self.source), 'repeated_speech', .2, .5, 'repeat', '快快'),
                 'check_id': 'repeated_speech', 'start': .2, 'end': .5, 'text': '快快', 'review_required': True}
        self.report['alerts'] = [alert]
        self.report['quality_status'] = 'review_required'
        self.report['checks']['repeated_speech']['result'] = 'review_required'
        return alert

    def reviewer(self):
        return {'kind': 'user', 'method': 'user_listening', 'quote': 'synthetic test statement', 'recorded_at': 'fixture timestamp'}

    def evidence(self):
        return [{'path': self.confirmation.name, 'sha256': file_hash(self.confirmation), 'kind': 'listening_confirmation'}]

    def resolve_alert(self, outcome='retain_normal_repetition'):
        alert = self.alert()
        self.save()
        self.resolutions = {'schema_version': 1, 'report_sha256': file_hash(self.report_path),
                            'source_sha256': file_hash(self.source), 'alerts': [
                                {'alert_id': alert['id'], 'outcome': outcome, 'assessment': 'synthetic normal emphasis',
                                 'reviewer': self.reviewer(), 'evidence': self.evidence()}], 'check_resolutions': []}

    def test_full_executed_clean_report_has_no_automatic_listening_claim(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(self.report['command_status'], 'completed')
        self.assertIn('not performed', self.report['human_listening'])

    def test_unresolved_alert_cannot_be_hidden_by_zero_counts_or_passed_status(self):
        self.alert()
        self.report['blocking_counts'] = {'unresolved': 0}
        self.report['quality_status'] = 'passed'
        self.assertTrue(any('unresolved' in e for e in self.check()))

    def test_normal_repetition_may_be_retained_with_version_bound_user_evidence(self):
        self.resolve_alert()
        self.assertEqual(self.check(), [])

    def test_agent_with_actual_audio_capability_is_allowed_as_structural_record(self):
        self.resolve_alert()
        self.resolutions['alerts'][0]['reviewer'] = {'kind': 'agent', 'method': 'agent_audio_listening',
                                                    'capability': 'audio_listening', 'quote': 'synthetic listened assertion',
                                                    'recorded_at': 'fixture timestamp'}
        self.assertEqual(self.check(), [])
        self.resolutions['alerts'][0]['reviewer']['method'] = 'asr_transcript_only'
        self.assertTrue(any('not listening' in e for e in self.check()))

    def machine_resolution(self):
        self.resolve_alert('false_positive')
        item = self.resolutions['alerts'][0]
        item['reviewer'] = {'kind': 'agent', 'method': 'machine_evidence_review',
                            'recorded_at': 'synthetic fixture timestamp',
                            'quote': 'Synthetic ASR/timing comparison, not actual listening.'}
        item['assessment'] = 'Synthetic machine evidence supports normal repetition in the flagged range.'
        item['evidence'] = [{'kind': 'machine_verification', 'path': self.confirmation.name,
                             'sha256': file_hash(self.confirmation)}]
        return item

    def test_machine_evidence_can_resolve_without_listening_capability(self):
        item = self.machine_resolution()
        self.assertNotIn('capability', item['reviewer'])
        self.assertEqual(self.check(), [])
        self.assertIn('not performed', self.report['human_listening'])

    def test_machine_evidence_must_be_hashed_current_and_typed(self):
        item = self.machine_resolution()
        item['evidence'][0]['kind'] = 'local_audio'
        self.assertTrue(any('machine_verification' in e for e in self.check()))
        item['evidence'][0]['kind'] = 'machine_verification'
        item['evidence'][0]['sha256'] = '0' * 64
        self.assertTrue(any('evidence changed' in e for e in self.check()))
        item['evidence'][0]['sha256'] = file_hash(self.confirmation)
        self.confirmation.unlink()
        self.assertTrue(any('evidence file missing' in e for e in self.check()))

    def test_machine_review_cannot_be_relabelled_as_listening(self):
        item = self.machine_resolution()
        item['evidence'][0]['kind'] = 'listening_confirmation'
        self.assertTrue(any('cannot label' in e for e in self.check()))
        item['evidence'][0]['kind'] = 'machine_verification'
        item['human_listening_performed'] = True
        self.assertTrue(any('cannot claim performed' in e for e in self.check()))

    def test_machine_reviewer_still_needs_assessment_time_and_statement(self):
        item = self.machine_resolution()
        item['assessment'] = ''
        self.assertTrue(any('assessment' in e for e in self.check()))
        item['assessment'] = 'synthetic assessment'
        item['reviewer']['quote'] = ''
        self.assertTrue(any('time and statement' in e for e in self.check()))

    def test_unavailable_requires_evidenced_machine_full_media_supplement(self):
        item = self.machine_resolution()
        self.report['checks']['word_integrity'].update(status='unavailable', result='unverified',
                                                      reason='synthetic technical check was unavailable')
        self.save()
        self.resolutions['report_sha256'] = file_hash(self.report_path)
        self.assertTrue(any('unverified' in e for e in self.check()))
        self.resolutions['check_resolutions'] = [{
            'check_id': 'word_integrity', 'outcome': 'verified', 'coverage': full_coverage(2),
            'assessment': 'Synthetic full-media machine timing comparison, not phoneme listening.',
            'reviewer': dict(item['reviewer']), 'evidence': list(item['evidence'])}]
        self.assertEqual(self.check(), [])
        self.resolutions['check_resolutions'][0]['coverage']['end'] = 1
        self.assertTrue(any('full-media coverage' in e for e in self.check()))

    def test_unresolved_real_alert_not_cleared_by_machine_check_supplement(self):
        self.machine_resolution()
        self.resolutions['alerts'] = []
        self.assertTrue(any('unresolved review_required' in e for e in self.check()))

    def test_explanation_without_evidence_does_not_resolve(self):
        self.resolve_alert()
        self.resolutions['alerts'][0]['evidence'] = []
        self.assertTrue(self.check())

    def test_evidence_modified_or_missing_invalidates_resolution(self):
        self.resolve_alert()
        self.confirmation.write_text('modified fixture evidence', encoding="utf-8")
        self.assertTrue(any('evidence changed' in e for e in self.check()))
        self.confirmation.unlink()
        self.assertTrue(any('evidence file missing' in e for e in self.check()))

    def test_wrong_media_version_invalidates_report_and_resolution(self):
        self.resolve_alert()
        self.source.write_bytes(b'a new media revision')
        self.assertTrue(any('another media version' in e for e in self.check()))

    def test_changed_machine_report_invalidates_resolutions(self):
        self.resolve_alert()
        self.report['run_note'] = 'machine report changed'
        self.assertTrue(any('another residual report' in e for e in self.check()))

    def test_fixed_cannot_clear_same_old_report(self):
        self.resolve_alert('fixed')
        self.assertTrue(any('fresh media/report' in e for e in self.check()))

    def test_skipped_unavailable_partial_and_unverified_checks_block(self):
        for field, value in [('status', 'skipped'), ('status', 'unavailable'), ('result', 'unverified'),
                             ('coverage', {'scope': 'partial', 'start': 0, 'end': .5})]:
            original = self.report['checks']['word_integrity'].copy()
            self.report['checks']['word_integrity'].update({field: value, 'reason': 'synthetic missing capability'})
            self.assertTrue(any('unverified' in e for e in self.check()))
            self.report['checks']['word_integrity'] = original

    def test_unavailable_can_have_evidenced_full_media_listening_supplement(self):
        self.report['checks']['word_integrity'].update({'status': 'unavailable', 'result': 'unverified',
                                                       'reason': 'ASR cannot establish word completeness'})
        self.report['quality_status'] = 'unverified'
        self.save()
        self.resolutions = {'schema_version': 1, 'report_sha256': file_hash(self.report_path), 'source_sha256': file_hash(self.source),
                            'alerts': [], 'check_resolutions': [{'check_id': 'word_integrity', 'outcome': 'verified',
                            'coverage': full_coverage(2.0), 'assessment': 'synthetic full-media listening assertion',
                            'reviewer': self.reviewer(), 'evidence': self.evidence()}]}
        self.assertEqual(self.check(), [])
        self.resolutions['check_resolutions'][0]['coverage']['end'] = 1
        self.assertTrue(any('full-media coverage' in e for e in self.check()))

    def test_legacy_no_checks_alerts_and_global_review_required_without_issue_block(self):
        current = self.report
        self.report = {'stage': 'residual-check', 'status': 'review_required', 'blocking_counts': {'unresolved': 0}}
        self.assertTrue(self.check())
        self.report = current
        self.report['quality_status'] = 'review_required'
        self.assertTrue(any('no tracked issue' in e for e in self.check()))

    def test_check_review_required_without_alert_cannot_be_assumed_passed(self):
        self.report['checks']['breath_gaps']['result'] = 'review_required'
        self.report['quality_status'] = 'review_required'
        self.assertTrue(self.check())

    def test_duplicate_and_unknown_alert_resolution_block(self):
        self.resolve_alert()
        self.report['alerts'].append(self.report['alerts'][0].copy())
        self.assertTrue(any('duplicate alert ID' in e for e in self.check()))
        self.report['alerts'].pop()
        self.save(); self.resolutions['report_sha256'] = file_hash(self.report_path)
        self.resolutions['alerts'][0]['alert_id'] = 'unknown'
        self.assertTrue(any('unknown alert' in e for e in self.check()))

    def test_report_and_resolutions_reference_hashes_verified(self):
        self.resolve_alert(); self.save()
        self.assertTrue(validate_review(self.report_path, self.source, self.resolutions_path, '0' * 64, '0' * 64))
        self.assertEqual(validate_review(self.report_path, self.source, self.resolutions_path,
                                         file_hash(self.report_path), file_hash(self.resolutions_path)), [])

    def test_stable_id_and_false_review_required_cannot_hide_issue(self):
        first = stable_alert_id('a' * 64, 'repeated_speech', .1, .2, 'repeat', '我我')
        self.assertEqual(first, stable_alert_id('a' * 64, 'repeated_speech', .1, .2, 'repeat', '我我'))
        self.assertNotEqual(first, stable_alert_id('b' * 64, 'repeated_speech', .1, .2, 'repeat', '我我'))
        self.alert()['review_required'] = False
        self.assertTrue(any('cannot bypass' in e for e in self.check()))

    def test_command_failed_and_malformed_objects_block(self):
        self.report['command_status'] = 'failed'
        self.assertTrue(self.check())
        self.report_path.write_text('[]', encoding="utf-8")
        self.assertTrue(validate_review(self.report_path, self.source))

    def test_missing_lineage_or_changed_map_blocks_even_with_full_current_checks(self):
        lineage = self.report.pop('source_review_lineage')
        self.assertTrue(any('lineage unavailable' in e for e in self.check()))
        self.report['source_review_lineage'] = lineage
        Path(lineage['edit_map']['path']).write_text('{}', encoding="utf-8")
        self.assertTrue(any('missing or changed' in e for e in self.check()))

    def test_source_alerts_cannot_disappear_or_be_marked_fixed_by_editing(self):
        lineage = self.report['source_review_lineage']
        upstream_path = Path(lineage['report']['path'])
        upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
        upstream['alerts'] = [{'id': 'source-warning', 'check_id': 'repeated_speech', 'start': .1, 'end': .3,
                              'review_required': True}]
        upstream_path.write_text(json.dumps(upstream), encoding="utf-8")
        lineage['report']['sha256'] = file_hash(upstream_path)
        mapping_path = Path(lineage['edit_map']['path'])
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        mapping['analysis_review'] = lineage['report']
        mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
        lineage['edit_map']['sha256'] = file_hash(mapping_path)
        self.assertTrue(any('was discarded' in e for e in self.check()))
        self.report['alerts'] = [{'id': 'mapped-warning', 'check_id': 'repeated_speech', 'start': .1, 'end': .3,
                                 'review_required': False, 'severity': 'informational',
                                 'upstream_alert_id': 'source-warning', 'upstream_report_sha256': lineage['report']['sha256']}]
        self.assertTrue(any('editing alone' in e for e in self.check()))

    def test_local_review_cannot_masquerade_as_full_residual_review(self):
        self.report['stage'] = 'local-review'
        self.assertTrue(any('wrong residual' in e for e in self.check()))
        self.report['stage'] = 'residual-check'
        for check in self.report['checks'].values():
            check['coverage']['scope'] = 'local_windows'
        self.assertTrue(any('full-media check' in e for e in self.check()))

    def test_each_source_alert_mapping_portion_and_exact_deletion_boundary_required(self):
        lineage = self.report['source_review_lineage']
        upstream_path = Path(lineage['report']['path'])
        upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
        upstream['alerts'] = [{'id':'cross-cut', 'check_id':'repeated_speech', 'start':.2, 'end':1.8, 'review_required':True}]
        mapping_path = Path(lineage['edit_map']['path'])
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        mapping['kept_segments'] = [
            {'source_start':0,'source_end':.5,'output_start':0,'output_end':.5},
            {'source_start':1.5,'source_end':2,'output_start':.5,'output_end':1}]
        def bind():
            upstream_path.write_text(json.dumps(upstream), encoding="utf-8")
            lineage['report']['sha256'] = file_hash(upstream_path)
            mapping['analysis_review'] = lineage['report']
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            lineage['edit_map']['sha256'] = file_hash(mapping_path)
            for alert in self.report['alerts']:
                alert['upstream_report_sha256'] = lineage['report']['sha256']
        self.report['duration_seconds'] = 1
        for check in self.report['checks'].values():
            check['coverage'] = full_coverage(1)
        self.report['alerts'] = [{'id':'portion-1','check_id':'repeated_speech','start':.2,'end':.5,
                                 'review_required':True,'upstream_alert_id':'cross-cut'}]
        bind()
        self.assertTrue(any('portion or deletion boundary' in e for e in self.check()))
        self.report['alerts'].append({'id':'portion-2','check_id':'repeated_speech','start':.5,'end':.8,
                                      'review_required':True,'upstream_alert_id':'cross-cut'})
        bind()
        self.assertFalse(any('portion or deletion boundary' in e for e in self.check()))
        # Entire warning now lies in the deleted 0.5-1.5 source region; the
        # required current window is [0.2,1.0] around output cut position .5.
        upstream['alerts'][0].update(start=.7,end=1.2)
        self.report['alerts'] = [{'id':'wrong-boundary','check_id':'repeated_speech','start':0,'end':.1,
                                 'review_required':True,'upstream_alert_id':'cross-cut'}]
        bind()
        self.assertTrue(any('portion or deletion boundary' in e for e in self.check()))
        self.report['alerts'][0].update(start=.2,end=1)
        bind()
        self.assertFalse(any('portion or deletion boundary' in e for e in self.check()))


if __name__ == '__main__':
    unittest.main()
