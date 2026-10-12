"""Synthetic consent/QA records test validation only, never claim real listening."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from stage_gate import CHECKS, validate_report
from workflow_mode import (create_authorization, file_hash, resolve_workflow,
                           settings_digest, validate_ai_review, validate_workflow)


class WorkflowModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'synthetic_source.bin'
        self.source.write_bytes(b'not actual media; authorization hash fixture')
        self.evidence = self.root / 'synthetic_consent.txt'
        self.evidence.write_text('模拟一次真实授权字段，仅测试，不代表真人授权或听校。', encoding='utf-8')
        self.qa = self.root / 'synthetic_qa.txt'
        self.qa.write_text('synthetic AI check fixture; no audio was listened to', encoding='utf-8')
        self.config = self.root / 'settings.json'
        self.authfile = self.root / 'authorization.json'
        self.reportfile = self.root / 'gate.json'
        self.choices = dict(retake_policy='none', font_name='test font', mask_shape='circle',
                            background='skill_default', background_motion='static', delivery='mp4_and_jianying')
        self.settings = {'schema_version': 1, 'pipeline': {'captions': {'font_size': 86}},
                         'confirmed_choices': copy.deepcopy(self.choices),
                         'workflow': {'mode': 'full_auto', 'state': 'pending', 'run_id': 'synthetic-run', 'revision': 1}}
        self.authorize()
        self.provenance = self.root / 'provenance_edit_map.json'
        self.write(self.provenance, {'source_sha256': file_hash(self.source), 'output_sha256': file_hash(self.source)})
        self.report = self.make_report('captions')

    def write(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')

    def authorize(self):
        self.auth = create_authorization(self.settings, [self.source], self.choices, self.evidence,
                                         message='synthetic explicit consent fixture', recorded_at='fixture time',
                                         settings_path=self.config)
        self.write(self.authfile, self.auth)
        self.settings['workflow'].update(state='active', authorization={'path': str(self.authfile), 'sha256': file_hash(self.authfile)})
        self.write(self.config, self.settings)
        self.record = {'mode': 'full_auto', 'settings': {'path': str(self.config)},
                       'authorization': copy.deepcopy(self.settings['workflow']['authorization'])}

    def make_report(self, stage):
        return {'stage': stage, 'workflow': copy.deepcopy(self.record),
                'source_provenance': {'edit_map': {'path': str(self.provenance), 'sha256': file_hash(self.provenance)}},
                'artifacts': {'source': {'sha256': file_hash(self.source)}},
                'checks': {key: {'status': 'passed', 'method': 'synthetic fixture', 'evidence': [str(self.qa)]}
                           for key in CHECKS[stage]},
                'blocking_counts': dict(approved_not_executed=0, known_unfixed=0, unresolved=0),
                'ai_review': {'status': 'passed', 'reviewer_id': 'synthetic-reviewer',
                              'method': 'combined_evidence_review',
                              'evidence': [{'path': str(self.qa), 'sha256': file_hash(self.qa), 'kind': 'machine_verification'}],
                              'artifacts': {'source': {'sha256': file_hash(self.source)}},
                              'covered_checks': list(CHECKS[stage])}}

    def gate(self, stage='captions', project_config=True):
        self.write(self.reportfile, self.report)
        return validate_report(self.reportfile, stage, {'source': self.source},
                               project_config=self.config if project_config else None)

    def test_full_auto_uses_once_authorization_and_ai_review(self):
        self.assertEqual(self.gate(), [])
        self.assertNotIn('user_approval', self.report)

    def test_locates_actual_settings_without_explicit_config(self):
        self.assertEqual(self.gate(project_config=False), [])

    def test_creation_does_not_mutate_settings(self):
        before = copy.deepcopy(self.settings)
        create_authorization(self.settings, [self.source], self.choices, self.evidence,
                             message='fixture', recorded_at='fixture')
        self.assertEqual(self.settings, before)

    def test_workflow_state_excluded_but_effective_choices_bound(self):
        before = settings_digest(self.settings)
        changed = copy.deepcopy(self.settings)
        changed['workflow']['state'] = 'paused'
        self.assertEqual(settings_digest(changed), before)
        changed['pipeline']['captions']['font_size'] += 1
        self.assertNotEqual(settings_digest(changed), before)

    def test_missing_initial_choices_cannot_authorize(self):
        for key in self.choices:
            choices = dict(self.choices)
            del choices[key]
            with self.assertRaises(ValueError):
                create_authorization(self.settings, [self.source], choices, self.evidence, message='fixture', recorded_at='fixture')

    def test_invalid_motion_choice_cannot_authorize(self):
        for motion in ('right', {'direction': 'right', 'speed': 0}, {'direction': 'right', 'speed': float('inf')}):
            choices = dict(self.choices, background_motion=motion)
            settings = dict(self.settings, confirmed_choices=choices)
            with self.assertRaises(ValueError):
                create_authorization(settings, [self.source], choices, self.evidence, message='fixture', recorded_at='fixture')

    def test_pending_paused_unselected_blocks(self):
        for state in ('pending', 'paused'):
            self.settings['workflow']['state'] = state
            self.write(self.config, self.settings)
            self.assertTrue(self.gate())
        self.settings['workflow'] = {'mode': None, 'state': 'pending'}
        self.write(self.config, self.settings)
        self.assertTrue(self.gate())

    def test_old_run_or_revision_blocks(self):
        for key, value in [('run_id', 'new-run'), ('revision', 2)]:
            settings = copy.deepcopy(self.settings)
            settings['workflow'][key] = value
            self.write(self.config, settings)
            self.assertTrue(self.gate())

    def test_effective_setting_or_choice_changes_block(self):
        for modify in ('pipeline', 'choices'):
            settings = copy.deepcopy(self.settings)
            if modify == 'pipeline':
                settings['pipeline']['captions']['font_size'] = 90
            else:
                settings['confirmed_choices']['font_name'] = 'other font'
            self.write(self.config, settings)
            self.assertTrue(self.gate())

    def test_original_source_change_blocks_later_derived_stage(self):
        derived = self.root / 'derived.bin'
        derived.write_bytes(b'derived fixture')
        self.write(self.provenance, {'source_sha256': file_hash(self.source), 'output_sha256': file_hash(derived)})
        self.report['source_provenance']['edit_map']['sha256'] = file_hash(self.provenance)
        self.report['artifacts']['source']['sha256'] = file_hash(derived)
        self.report['ai_review']['artifacts']['source']['sha256'] = file_hash(derived)
        self.write(self.reportfile, self.report)
        self.assertEqual(validate_report(self.reportfile, 'captions', {'source': derived}, self.config), [])
        self.source.write_bytes(b'changed original source')
        self.assertTrue(validate_report(self.reportfile, 'captions', {'source': derived}, self.config))

    def test_authorization_bytes_and_selected_reference_must_match(self):
        self.authfile.write_text(self.authfile.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        self.assertTrue(self.gate())

    def test_changed_or_missing_user_evidence_blocks(self):
        self.evidence.write_text('changed', encoding='utf-8')
        self.assertTrue(self.gate())
        self.evidence.unlink()
        self.assertTrue(self.gate())

    def test_report_cannot_self_select_full_auto(self):
        self.settings['workflow'] = {'mode': 'semi_auto', 'state': 'active'}
        self.write(self.config, self.settings)
        self.assertTrue(any('mode differs' in e for e in self.gate()))

    def test_actual_full_auto_requires_report_reference(self):
        self.report.pop('workflow')
        self.assertTrue(self.gate())

    def test_copied_active_settings_cannot_bypass_paused_live_project(self):
        old = self.root / 'old_active.json'
        self.write(old, self.settings)
        self.settings['workflow'].update(state='paused', revision=2)
        self.write(self.config, self.settings)
        record = copy.deepcopy(self.record)
        record['settings']['path'] = str(old)
        self.assertTrue(any('authorized live project' in e for e in validate_workflow(record, self.root)))

    def test_inferred_settings_require_authorization_bound_path(self):
        self.auth.pop('settings_path')
        self.write(self.authfile, self.auth)
        ref = {'path': str(self.authfile), 'sha256': file_hash(self.authfile)}
        self.settings['workflow']['authorization'] = ref
        self.write(self.config, self.settings)
        record = dict(self.record, authorization=ref)
        self.assertTrue(validate_workflow(record, self.root))
        self.assertEqual(validate_workflow(record, self.root, self.config), [])

    def test_report_cannot_point_to_other_settings(self):
        other = self.root / 'other.json'
        self.write(other, self.settings)
        self.report['workflow']['settings']['path'] = str(other)
        self.assertTrue(self.gate())

    def test_full_auto_rejects_fake_stage_user_approval(self):
        self.report['user_approval'] = {'status': 'approved'}
        self.assertTrue(any('not a stage user_approval' in e for e in self.gate()))

    def test_missing_ai_review_blocks(self):
        self.report.pop('ai_review')
        self.assertTrue(self.gate())

    def test_machine_review_passes_without_audio_capability(self):
        for method in ('combined_evidence_review', 'machine_evidence_review'):
            self.report['ai_review']['method'] = method
            self.assertNotIn('capability', self.report['ai_review'])
            self.assertEqual(self.gate(), [])
        self.report['ai_review']['method'] = 'asr_only'
        self.assertTrue(self.gate())  # Unsupported QA record, not lack of ears.

    def test_all_media_stages_reject_static_but_allow_machine_assessment(self):
        from review_state import REQUIRED_CHECKS, full_coverage, make_report
        residual = make_report(self.source, 1.0, {
            key: {'status': 'executed', 'result': 'passed', 'method': 'synthetic machine fixture',
                  'coverage': full_coverage(1.0)} for key in REQUIRED_CHECKS}, [])
        residual['source_review_lineage'] = self.bound_lineage(self.source, self.source)
        residual_path = self.root / 'media_stage_residual.json'
        self.write(residual_path, residual)
        for stage in ('analysis', 'analyze', 'rough-cut', 'captions', 'preview'):
            with self.subTest(stage=stage):
                self.report = self.make_report(stage)
                if stage == 'rough-cut':
                    self.report['residual_review'] = {'report': {
                        'path': str(residual_path), 'sha256': file_hash(residual_path)}}
                for method in ('static_inspection', 'structural_review'):
                    self.report['ai_review']['method'] = method
                    self.assertTrue(any('static structure alone' in e for e in self.gate(stage)))
                for method in ('combined_evidence_review', 'machine_evidence_review'):
                    self.report['ai_review']['method'] = method
                    self.assertNotIn('capability', self.report['ai_review'])
                    self.assertEqual(self.gate(stage), [])

    def test_agent_audio_claim_requires_matching_capability_and_confirmation(self):
        self.report['ai_review'].update(method='agent_av_review', capability='audio_listening')
        self.assertTrue(self.gate())
        self.report['ai_review']['capability'] = 'audio_video_review'
        self.assertTrue(self.gate())  # A listening method cannot borrow machine evidence.
        self.report['ai_review']['evidence'][0]['kind'] = 'listening_confirmation'
        self.assertEqual(self.gate(), [])  # Synthetic legacy record, no actual listening claim.

    def test_machine_review_cannot_fake_listening_or_skip_typed_evidence(self):
        self.report['ai_review']['method'] = 'machine_evidence_review'
        self.report['ai_review']['evidence'][0].pop('kind')
        self.assertTrue(self.gate())
        self.report['ai_review']['evidence'][0]['kind'] = 'machine_verification'
        self.report['ai_review']['human_listening_performed'] = True
        self.assertTrue(self.gate())
        self.report['ai_review'].pop('human_listening_performed')
        self.report['ai_review']['evidence'][0]['kind'] = 'listening_confirmation'
        self.assertTrue(self.gate())

    def test_ai_evidence_and_coverage_and_artifact_are_bound(self):
        original = copy.deepcopy(self.report)
        for key, value in [('evidence', []), ('covered_checks', ['C1']), ('artifacts', {}), ('reviewer_id', ''), ('status', 'pending')]:
            self.report = copy.deepcopy(original)
            self.report['ai_review'][key] = value
            self.assertTrue(self.gate())
        self.report = copy.deepcopy(original)
        self.qa.write_text('changed QA fixture', encoding='utf-8')
        self.assertTrue(self.gate())

    def test_quality_counts_and_checks_not_relaxed(self):
        self.report['blocking_counts']['unresolved'] = 1
        self.assertTrue(self.gate())
        self.report['blocking_counts']['unresolved'] = 0
        self.report['checks']['C2']['status'] = 'unverified'
        self.assertTrue(self.gate())

    def test_legacy_semi_auto_still_requires_user_approval(self):
        self.settings.pop('workflow')
        self.write(self.config, self.settings)
        self.report.pop('workflow')
        self.assertTrue(self.gate())
        self.report['user_approval'] = {'status': 'approved', 'message': 'synthetic fixture',
                                       'recorded_at': 'fixture', 'evidence': str(self.evidence)}
        self.assertEqual(self.gate(), [])

    def test_analysis_alias_and_source_membership(self):
        self.report = self.make_report('analyze')
        self.assertEqual(self.gate('analysis'), [])
        other = self.root / 'unauthorized.bin'
        other.write_bytes(b'other original')
        self.report['artifacts']['source']['sha256'] = file_hash(other)
        self.report['ai_review']['artifacts']['source']['sha256'] = file_hash(other)
        self.write(self.reportfile, self.report)
        self.assertTrue(any('authorized original' in e for e in validate_report(self.reportfile, 'analysis', {'source': other}, self.config)))

    def test_native_basic_static_check_does_not_require_deep_ui(self):
        self.report = self.make_report('jianying-basic')
        self.report['ai_review']['method'] = 'static_inspection'
        self.report['ai_review'].pop('capability', None)
        self.assertEqual(self.gate('jianying-basic'), [])

    def test_semi_auto_native_basic_has_no_additional_user_approval(self):
        self.settings['workflow'] = {'mode': 'semi_auto', 'state': 'active'}
        self.write(self.config, self.settings)
        self.report = self.make_report('jianying-basic')
        self.report['workflow'] = {'mode': 'semi_auto', 'settings': {'path': str(self.config)}}
        self.report['ai_review']['method'] = 'structural_review'
        self.assertNotIn('user_approval', self.report)
        self.assertEqual(self.gate('jianying-basic'), [])
        del self.report['checks']['B2']
        self.assertTrue(self.gate('jianying-basic'))

    def test_semi_auto_audio_stage_still_requires_specific_user_approval(self):
        self.settings['workflow'] = {'mode': 'semi_auto', 'state': 'active'}
        self.write(self.config, self.settings)
        self.report['workflow'] = {'mode': 'semi_auto', 'settings': {'path': str(self.config)}}
        self.assertTrue(any('not approved by user' in e for e in self.gate()))

    def test_frozen_snapshot_explicit_offline_only(self):
        record = dict(self.record, frozen_snapshot=True,
                      user_evidence={'path': str(self.evidence), 'sha256': file_hash(self.evidence)})
        record['settings'] = {'path': str(self.config), 'sha256': file_hash(self.config)}
        self.assertTrue(validate_workflow(record, self.root))
        self.assertEqual(validate_workflow(record, self.root, live_config_required=False), [])
        self.source.unlink()
        self.assertEqual(validate_workflow(record, self.root, live_config_required=False), [])
        record['user_evidence']['sha256'] = '0' * 64
        self.assertTrue(validate_workflow(record, self.root, live_config_required=False))

    def test_frozen_preview_provenance_relative_map_remains_required(self):
        derived = self.root / 'frozen_derived.bin'
        derived.write_bytes(self.source.read_bytes())
        self.report = self.make_report('preview')
        self.report['workflow'].update(frozen_snapshot=True,
            user_evidence={'path': str(self.evidence), 'sha256': file_hash(self.evidence)})
        self.report['workflow']['settings']['sha256'] = file_hash(self.config)
        self.report['source_provenance']['edit_map']['path'] = self.provenance.name
        self.write(self.reportfile, self.report)
        self.source.unlink()
        self.assertEqual(validate_report(self.reportfile, 'preview', {'source': derived},
                                         live_config_required=False), [])
        self.provenance.write_text('{}', encoding='utf-8')
        self.assertTrue(validate_report(self.reportfile, 'preview', {'source': derived},
                                        live_config_required=False))

    def test_unmarked_offline_record_rejected(self):
        self.assertTrue(validate_workflow(self.record, self.root, live_config_required=False))

    def test_selected_asset_hash_change_blocks(self):
        background = self.root / 'background.bin'
        background.write_bytes(b'background fixture')
        self.choices['background'] = {'path': str(background), 'sha256': file_hash(background)}
        self.settings['confirmed_choices'] = copy.deepcopy(self.choices)
        self.authorize()
        self.report = self.make_report('captions')
        self.assertEqual(self.gate(), [])
        background.write_bytes(b'changed background')
        self.assertTrue(self.gate())

    def test_rough_cut_residual_still_required_in_full_auto(self):
        self.report = self.make_report('rough-cut')
        self.assertTrue(any('residual-review' in e for e in self.gate('rough-cut')))

    def bound_lineage(self, original, derived):
        from review_state import REQUIRED_CHECKS, full_coverage, make_report
        analysis = make_report(original, 1.0, {
            key: {'status': 'executed', 'result': 'passed', 'method': 'synthetic fixture',
                  'coverage': full_coverage(1.0)} for key in REQUIRED_CHECKS}, [])
        analysis['stage'] = 'analyze'
        analysis_path = self.root / 'bound_analysis.json'
        self.write(analysis_path, analysis)
        ref = {'path': str(analysis_path), 'sha256': file_hash(analysis_path), 'source_sha256': file_hash(original)}
        mapping = self.root / 'bound_map.json'
        self.write(mapping, {'source_sha256': file_hash(original), 'output_sha256': file_hash(derived),
                             'analysis_review': ref, 'kept_segments': [{'source_start': 0, 'source_end': 1,
                                                                      'output_start': 0, 'output_end': 1}]})
        return {'status': 'executed', 'edit_map': {'path': str(mapping), 'sha256': file_hash(mapping)}, 'report': ref}

    def test_full_auto_rough_cut_cannot_use_other_original_lineage(self):
        from review_state import REQUIRED_CHECKS, full_coverage, make_report
        other = self.root / 'other_original.bin'
        other.write_bytes(b'unauthorized original B fixture')
        residual = make_report(self.source, 1.0, {
            key: {'status': 'executed', 'result': 'passed', 'method': 'synthetic fixture',
                  'coverage': full_coverage(1.0)} for key in REQUIRED_CHECKS}, [])
        residual['source_review_lineage'] = self.bound_lineage(other, self.source)
        residual_path = self.root / 'residual.json'
        self.write(residual_path, residual)
        self.report = self.make_report('rough-cut')
        self.report['residual_review'] = {'report': {'path': str(residual_path), 'sha256': file_hash(residual_path)}}
        self.assertTrue(any('source lineage is not authorized' in e for e in self.gate('rough-cut')))

    def test_derived_media_provenance_missing_changed_or_wrong_original_blocks(self):
        original = copy.deepcopy(self.report)
        del self.report['source_provenance']
        self.assertTrue(self.gate())
        self.report = copy.deepcopy(original)
        self.provenance.write_text('{}', encoding='utf-8')
        self.assertTrue(self.gate())
        self.write(self.provenance, {'source_sha256': '0' * 64, 'output_sha256': file_hash(self.source)})
        self.report['source_provenance']['edit_map']['sha256'] = file_hash(self.provenance)
        self.assertTrue(any('original source is not authorized' in e for e in self.gate()))

    def test_derived_provenance_wrong_output_blocks(self):
        self.write(self.provenance, {'source_sha256': file_hash(self.source), 'output_sha256': '0' * 64})
        self.report['source_provenance']['edit_map']['sha256'] = file_hash(self.provenance)
        self.assertTrue(any('another output media' in e for e in self.gate()))

    def test_full_auto_cannot_hide_unresolved_residual_alert(self):
        from review_state import REQUIRED_CHECKS, full_coverage, make_report
        from test_review_state import synthetic_lineage
        residual = make_report(self.source, 1.0, {
            key: {'status': 'executed', 'result': 'passed', 'method': 'synthetic detector fixture',
                  'coverage': full_coverage(1.0)} for key in REQUIRED_CHECKS}, [])
        residual['source_review_lineage'] = self.bound_lineage(self.source, self.source)
        residual_path = self.root / 'residual.json'
        self.write(residual_path, residual)
        self.report = self.make_report('rough-cut')
        self.report['residual_review'] = {'report': {'path': str(residual_path), 'sha256': file_hash(residual_path)}}
        self.assertEqual(self.gate('rough-cut'), [])
        residual['alerts'] = [{'id': 'synthetic-alert', 'check_id': 'repeated_speech',
                               'start': .2, 'end': .4, 'review_required': True}]
        residual['quality_status'] = 'review_required'
        self.write(residual_path, residual)
        self.report['residual_review']['report']['sha256'] = file_hash(residual_path)
        self.assertTrue(any('unresolved review_required' in e for e in self.gate('rough-cut')))

    def test_malformed_ai_method_returns_errors(self):
        self.report['ai_review']['method'] = {'unexpected': 'object'}
        self.assertTrue(validate_ai_review(self.report, {'source': self.source}, CHECKS['captions'],
                                          self.root, require_audio=True))

    def test_empty_or_non_user_authorization_record_blocks(self):
        self.auth['user_authorization']['kind'] = 'agent'
        self.write(self.authfile, self.auth)
        ref = {'path': str(self.authfile), 'sha256': file_hash(self.authfile)}
        self.settings['workflow']['authorization'] = ref
        self.write(self.config, self.settings)
        self.report['workflow']['authorization'] = ref
        self.assertTrue(self.gate())


if __name__ == '__main__':
    unittest.main()
