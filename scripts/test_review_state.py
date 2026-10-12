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

    def semantic_evidence(self, target_key, target_id, coverage, verification,
                          kind='machine_verification', path=None, **bindings):
        path = path or self.confirmation
        record = {'schema_version': 2, 'kind': kind, 'source_sha256': file_hash(self.source),
                  target_key: target_id, 'coverage': dict(coverage), 'verification': verification,
                  'observations': [{'method': 'synthetic timing and source-map comparison',
                                    'finding': 'SYNTHETIC fixture: both repeated tokens map to the retained 0.2-0.5 second range; this is not real speech acceptance.'}],
                  **bindings}
        path.write_text(json.dumps(record), encoding='utf-8')
        return [{'path': path.name, 'sha256': file_hash(path), 'kind': kind}]

    def resolve_alert(self, outcome='retain_normal_repetition'):
        alert = self.alert()
        self.save()
        verification = 'confirmed_issue' if outcome == 'fixed' else 'confirmed_benign'
        coverage = {'scope': 'alert_window', 'start': alert['start'], 'end': alert['end']}
        self.resolutions = {'schema_version': 2, 'report_sha256': file_hash(self.report_path),
                            'source_sha256': file_hash(self.source), 'alerts': [
                                {'alert_id': alert['id'], 'decision': 'repair' if outcome == 'fixed' else 'retain',
                                 'verification': verification, 'coverage': coverage,
                                 'assessment': 'synthetic normal emphasis', 'reviewer': self.reviewer(),
                                 'evidence': self.semantic_evidence('alert_id', alert['id'], coverage, verification,
                                                                    kind='listening_confirmation')}], 'check_resolutions': []}

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
        item['evidence'] = self.semantic_evidence('alert_id', item['alert_id'], item['coverage'], item['verification'])
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
            'check_id': 'word_integrity', 'verification': 'confirmed', 'coverage': full_coverage(2),
            'assessment': 'Synthetic full-media machine timing comparison, not phoneme listening.',
            'reviewer': dict(item['reviewer']),
            'evidence': self.semantic_evidence('check_id', 'word_integrity', full_coverage(2), 'confirmed',
                                                path=self.root/'machine-check.json')}]
        self.assertEqual(self.check(), [])
        self.resolutions['check_resolutions'][0]['coverage']['end'] = 1
        self.assertTrue(any('full-media coverage' in e for e in self.check()))

    def test_unresolved_real_alert_not_cleared_by_machine_check_supplement(self):
        self.machine_resolution()
        self.resolutions['alerts'] = []
        self.assertTrue(any('unresolved review_required' in e for e in self.check()))

    def details(self, **kwargs):
        self.save()
        return validate_review(self.report_path, self.source,
                               self.resolutions_path if self.resolutions is not None else None,
                               return_details=True, **kwargs)

    def rewrite_machine_evidence(self, item, update):
        path = self.root / item['evidence'][0]['path']
        record = json.loads(path.read_text(encoding='utf-8'))
        update(record)
        path.write_text(json.dumps(record), encoding='utf-8')
        item['evidence'][0]['sha256'] = file_hash(path)

    def test_inconclusive_retention_remains_unresolved_despite_zero_counts(self):
        item = self.machine_resolution()
        item['verification'] = 'inconclusive'
        self.rewrite_machine_evidence(item, lambda record: record.update(verification='inconclusive'))
        self.report['blocking_counts'] = {'unresolved': 0, 'known_unfixed': 0}
        self.report['quality_status'] = 'passed'
        self.save()
        self.resolutions['report_sha256'] = file_hash(self.report_path)
        result = self.details()
        self.assertEqual(item['decision'], 'retain')
        self.assertEqual(result['unresolved_count'], 1)
        self.assertEqual(result['blocking_counts']['unresolved'], 1)
        self.assertEqual(result['unresolved_alert_ids'], [item['alert_id']])
        self.assertTrue(any('inconclusive' in error for error in result['errors']))

    def test_retaining_confirmed_issue_does_not_make_it_a_false_positive(self):
        item = self.machine_resolution()
        item['verification'] = 'confirmed_issue'
        self.rewrite_machine_evidence(item, lambda record: record.update(verification='confirmed_issue'))
        result = self.details()
        self.assertEqual(result['unresolved_count'], 1)
        self.assertEqual(result['known_unfixed_count'], 1)
        self.assertTrue(result['errors'])

    def test_matching_machine_observations_can_confirm_retained_benign_alert(self):
        item = self.machine_resolution()
        result = self.details()
        self.assertNotIn('outcome', item)
        self.assertNotIn('capability', item['reviewer'])
        self.assertEqual((item['decision'], item['verification']), ('retain', 'confirmed_benign'))
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['blocking_counts'], {'unresolved': 0, 'known_unfixed': 0})

    def test_unrelated_or_partial_machine_evidence_cannot_clear_alert(self):
        variants = [
            ('source', lambda record: record.update(source_sha256='0' * 64)),
            ('target', lambda record: record.update(alert_id='another-alert')),
            ('missing binding', lambda record: record.pop('alert_id')),
            ('narrow range', lambda record: record.update(coverage={'scope': 'alert_window', 'start': .2, 'end': .3})),
            ('wrong scope', lambda record: record.update(coverage={'scope': 'arbitrary', 'start': .2, 'end': .5})),
            ('no observation', lambda record: record.update(observations=[])),
            ('empty finding', lambda record: record.update(observations=[{'method': 'asr', 'finding': ''}])),
            ('disagrees', lambda record: record.update(verification='inconclusive')),
        ]
        for label, update in variants:
            with self.subTest(label=label):
                item = self.machine_resolution()
                self.rewrite_machine_evidence(item, update)
                result = self.details()
                self.assertTrue(result['errors'])
                self.assertEqual(result['unresolved_count'], 1)

    def test_valid_hash_on_generic_receipt_is_not_semantic_evidence(self):
        item = self.machine_resolution()
        self.confirmation.write_text('Generic machine check passed', encoding='utf-8')
        item['evidence'][0]['sha256'] = file_hash(self.confirmation)
        result = self.details()
        self.assertTrue(any('structured observations' in error for error in result['errors']))
        self.assertEqual(result['unresolved_count'], 1)

    def test_report_hash_binding_becomes_stale_even_if_resolution_hash_is_updated(self):
        item = self.machine_resolution()
        self.rewrite_machine_evidence(item, lambda record: record.update(report_sha256=file_hash(self.report_path)))
        self.assertEqual(self.check(), [])
        self.report['additional_detector_run'] = 'changed report fixture'
        self.save()
        self.resolutions['report_sha256'] = file_hash(self.report_path)
        result = self.details()
        self.assertTrue(any('semantic evidence belongs to another residual report' in error for error in result['errors']))
        self.assertEqual(result['unresolved_count'], 1)

    def test_report_binding_without_target_id_still_requires_matching_scope(self):
        item = self.machine_resolution()
        def bind_report(record):
            record.pop('alert_id')
            record['report_sha256'] = file_hash(self.report_path)
        self.rewrite_machine_evidence(item, bind_report)
        self.assertEqual(self.check(), [])
        self.rewrite_machine_evidence(item, lambda record: record.update(coverage={'scope': 'alert_window', 'start': .7, 'end': 1}))
        self.assertTrue(any('coverage' in error for error in self.check()))

    def test_inconclusive_check_supplement_is_derived_unverified(self):
        self.report['checks']['word_integrity'].update(status='unavailable', result='unverified', reason='synthetic timing needs review')
        self.save()
        self.resolutions = {'schema_version': 2, 'report_sha256': file_hash(self.report_path),
                            'source_sha256': file_hash(self.source), 'alerts': [], 'check_resolutions': [{
                                'check_id': 'word_integrity', 'verification': 'inconclusive', 'coverage': full_coverage(2),
                                'assessment': 'Synthetic comparison cannot establish complete word-timing coverage.',
                                'reviewer': {'kind': 'agent', 'method': 'machine_evidence_review',
                                             'recorded_at': 'fixture timestamp', 'quote': 'Missing timing interval remains unresolved.'},
                                'evidence': self.semantic_evidence('check_id', 'word_integrity', full_coverage(2), 'inconclusive')}]}
        result = self.details()
        self.assertEqual(result['unverified_check_count'], 1)
        self.assertEqual(result['unverified_check_ids'], ['word_integrity'])
        self.assertEqual(result['blocking_counts']['unresolved'], 1)
        self.assertTrue(result['errors'])

    def test_failed_detector_cannot_be_overridden_by_confirmed_supplement(self):
        self.report['checks']['word_integrity']['result'] = 'failed'
        self.save()
        self.resolutions = {'schema_version': 2, 'report_sha256': file_hash(self.report_path),
                            'source_sha256': file_hash(self.source), 'alerts': [], 'check_resolutions': [{
                                'check_id': 'word_integrity', 'verification': 'confirmed', 'coverage': full_coverage(2),
                                'assessment': 'Synthetic claimed complete timing after a failed detector.',
                                'reviewer': {'kind': 'agent', 'method': 'machine_evidence_review',
                                             'recorded_at': 'fixture timestamp', 'quote': 'Synthetic claim.'},
                                'evidence': self.semantic_evidence('check_id', 'word_integrity', full_coverage(2), 'confirmed')}]}
        result = self.details()
        self.assertEqual(result['unverified_check_count'], 1)
        self.assertTrue(any('failed detector' in error for error in result['errors']))

    def test_legacy_resolution_cannot_bypass_v2_even_with_historical_opt_in(self):
        self.machine_resolution()
        self.resolutions['schema_version'] = 1
        for allow_legacy in (False, True):
            result = self.details(allow_legacy=allow_legacy)
            self.assertTrue(any('requires v2' in error for error in result['errors']))
            self.assertEqual(result['unresolved_count'], 1)

    def test_legacy_listening_history_is_explicitly_distinct_from_current_clearance(self):
        self.resolve_alert()
        self.report['schema_version'] = 1
        self.resolutions['schema_version'] = 1
        item = self.resolutions['alerts'][0]
        item.pop('decision'); item.pop('verification'); item.pop('coverage')
        item['outcome'] = 'retain_normal_repetition'
        self.confirmation.write_text('SYNTHETIC historical user-listening record; not actual listening.', encoding='utf-8')
        item['evidence'] = self.evidence()
        self.save()
        self.resolutions['report_sha256'] = file_hash(self.report_path)
        self.assertTrue(any('historical reading' in error for error in self.details()['errors']))
        result = self.details(allow_legacy=True)
        self.assertEqual(result['errors'], [])
        self.assertTrue(result['legacy'])
        self.assertEqual(result['status'], 'legacy_history')

    def test_legacy_outcome_cannot_hide_inconclusive_v2_verification(self):
        item = self.machine_resolution()
        item.update(outcome='false_positive', verification='inconclusive')
        self.rewrite_machine_evidence(item, lambda record: record.update(verification='inconclusive'))
        result = self.details()
        self.assertEqual(result['unresolved_count'], 1)
        self.assertTrue(any('legacy outcome' in error for error in result['errors']))

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
        self.resolutions = {'schema_version': 2, 'report_sha256': file_hash(self.report_path), 'source_sha256': file_hash(self.source),
                            'alerts': [], 'check_resolutions': [{'check_id': 'word_integrity', 'verification': 'confirmed',
                            'coverage': full_coverage(2.0), 'assessment': 'synthetic full-media listening assertion',
                            'reviewer': self.reviewer(), 'evidence': self.semantic_evidence('check_id', 'word_integrity',
                                full_coverage(2), 'confirmed', kind='listening_confirmation')}]}
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
