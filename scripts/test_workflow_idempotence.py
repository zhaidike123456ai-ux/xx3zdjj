"""Harmless job settings do not revoke consent; real content changes still do.

All files and consent messages are synthetic UTF-8 fixtures, never user media.
"""
import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path

import studio_manager as studio
from workflow_mode import (normalize_setting_value, settings_digest,
                           stage_settings_digest, validate_workflow)


def args(**values):
    return argparse.Namespace(**values)


class WorkflowIdempotenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'studio'
        self.source = self.base / '原片.mp4'
        self.source.write_bytes(b'synthetic source, never decoded')
        self.project = Path(studio.init_project(args(studio_root=str(self.root), title='合成测试',
            slug='idempotence', date='20261012', source=[str(self.source)], copy_inputs=False))['project'])
        self.config = studio.settings_path(self.project)
        self.evidence = self.base / '授权夹具.txt'
        self.evidence.write_text('SYNTHETIC consent fixture; not a real production authorization.', encoding='utf-8')
        font, background = self.base / 'font.ttf', self.base / 'background.png'
        font.write_bytes(b'synthetic font'); background.write_bytes(b'synthetic image')
        self.choices_file = self.base / 'choices.json'
        studio.write(self.choices_file, {'retake_policy': 'last_complete', 'font_name': 'Fixture',
            'font_file': str(font), 'mask_shape': 'circle', 'background': str(background),
            'background_motion': {'direction': 'right', 'speed': 25}, 'delivery': 'mp4_and_jianying'})

    def authorize(self, *, legacy=False):
        for action, mode in [('select', 'full_auto'), ('authorize', None)]:
            studio.configure_workflow(args(project=str(self.project), action=action, mode=mode,
                evidence_file=str(self.evidence), choices_file=str(self.choices_file)))
        if legacy:
            settings = studio.read(self.config)
            ref = settings['workflow']['authorization']
            auth = studio.read(ref['path'])
            auth.pop('settings_digest_version')
            auth['settings_digest'] = settings_digest(settings, version=1)
            studio.write(ref['path'], auth)
            ref['sha256'] = studio.sha(ref['path'])
            studio.write(self.config, settings)
        self.assertEqual(self.errors(), [])
        return copy.deepcopy(studio.read(self.config)['workflow']['authorization'])

    def errors(self):
        settings = studio.read(self.config)
        return validate_workflow(studio.workflow_record(settings, self.config), self.config.parent, self.config)

    def set(self, key, value):
        return studio.set_setting(args(project=str(self.project), key=key,
            value=json.dumps(value, ensure_ascii=False), evidence='SYNTHETIC setting request'))

    def preference(self, key, value, context='all'):
        return studio.preference(args(studio_root=str(self.root), action='record', key=key,
            value=json.dumps(value, ensure_ascii=False), scope='confirmed', evidence='SYNTHETIC preference', context=context))

    def apply_preferences(self, context='all'):
        return studio.apply_preferences(args(studio_root=str(self.root), project=str(self.project), context=context))

    def approved_artifact(self, *, legacy=False):
        media = self.project / '04_previews' / 'captions.ass'
        media.write_text('SYNTHETIC caption fixture', encoding='utf-8')
        row = studio.register_artifact(args(project=str(self.project), kind='captions', file=str(media), depends_on=[]))['artifact']
        studio.approve(args(project=str(self.project), artifact_id=row['id'], evidence='SYNTHETIC stage confirmation'))
        if legacy:
            _, path, manifest = studio.info(self.project)
            record = manifest['artifacts'][0]
            record.pop('settings_digest_version')
            record['settings_sha256'] = studio.object_hash(studio.read(self.config)['pipeline']['captions'])
            studio.write(path, manifest)
        return row['id']

    def artifact_state(self):
        return studio.status(args(project=str(self.project)))['artifacts'][0]['current_status']

    def test_same_value_and_equivalent_type_preserve_new_and_legacy_authorizations(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                reference = self.authorize(legacy=legacy)
                before = self.config.read_bytes()
                self.assertFalse(self.set('pipeline.preview.mask_shape', 'circle')['changed'])
                self.assertFalse(self.set('pipeline.captions.font_size', '86')['changed'])
                self.assertEqual(self.config.read_bytes(), before)
                self.assertEqual(studio.read(self.config)['workflow']['authorization'], reference)
                self.assertEqual(self.errors(), [])

    def test_runtime_output_threads_change_preserves_new_and_legacy_auth_without_rewriting_it(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                reference = self.authorize(legacy=legacy)
                original = Path(reference['path']).read_bytes()
                for key, value in [('output_dir', str(self.base / 'render_v2')),
                                   ('cpu_threads', 8), ('output_name', 'complete_v2.mp4')]:
                    self.set('pipeline.captions.' + key, value)
                    self.assertEqual(studio.read(self.config)['workflow']['state'], 'active')
                    self.assertEqual(self.errors(), [])
                self.assertEqual(Path(reference['path']).read_bytes(), original)
                self.assertEqual(studio.read(self.config)['workflow']['authorization'], reference)

    def test_legacy_baseline_cannot_conceal_real_size_or_background_change(self):
        self.authorize(legacy=True)
        self.set('pipeline.captions.cpu_threads', 6)
        settings = studio.read(self.config)
        self.assertIn('legacy_settings_binding', settings['workflow'])
        changed = copy.deepcopy(settings)
        changed['pipeline']['captions']['font_size'] += 1
        studio.write(self.config, changed)
        self.assertTrue(self.errors())
        changed = copy.deepcopy(settings)
        changed['pipeline']['preview']['background'] = 'other.png'
        studio.write(self.config, changed)
        self.assertTrue(self.errors())
        studio.write(self.config, settings)
        self.set('pipeline.captions.font_size', 90)
        self.assertEqual(studio.read(self.config)['workflow']['state'], 'pending')
        self.assertNotIn('authorization', studio.read(self.config)['workflow'])

    def test_same_preference_reapplication_does_not_revoke_authorization(self):
        self.preference('pipeline.captions.font_size', 90)
        self.apply_preferences()
        reference = self.authorize()
        for _ in range(2):
            self.assertEqual(self.apply_preferences()['keys'], [])
            self.assertEqual(self.errors(), [])
            self.assertEqual(studio.read(self.config)['workflow']['authorization'], reference)
        self.preference('pipeline.captions.font_size', 92)
        self.assertEqual(self.apply_preferences()['keys'], ['pipeline.captions.font_size'])
        self.assertEqual(studio.read(self.config)['workflow']['state'], 'pending')

    def test_generic_then_context_preference_does_not_temporarily_invalidate(self):
        self.preference('pipeline.captions.font_size', 82)
        self.preference('pipeline.captions.font_size', 86, 'portrait')
        self.apply_preferences('portrait')
        self.authorize()
        self.assertEqual(self.apply_preferences('portrait')['keys'], [])
        self.assertEqual(self.errors(), [])

    def test_artifact_new_and_legacy_bindings_survive_runtime_changes_but_not_real_style(self):
        self.authorize()
        self.approved_artifact(legacy=True)
        self.assertEqual(self.artifact_state(), 'approved')
        self.set('pipeline.captions.output_dir', str(self.base / 'output'))
        self.assertEqual(self.artifact_state(), 'approved')
        record = studio.info(self.project)[2]['artifacts'][0]
        self.assertEqual(record['settings_digest_version'], 2)
        self.set('pipeline.captions.cpu_threads', 8)
        self.assertEqual(self.artifact_state(), 'approved')
        self.set('pipeline.captions.pos_y', 1080)
        self.assertEqual(self.artifact_state(), 'settings_changed_approval_invalid')

    def test_direct_new_artifact_hash_ignores_runtime_and_numeric_representation(self):
        self.approved_artifact()
        settings = studio.read(self.config)
        settings['pipeline']['captions'].update(output='/tmp/output.mp4', cpu_threads=12, font_size='86')
        studio.write(self.config, settings)
        self.assertEqual(self.artifact_state(), 'approved')
        settings['pipeline']['captions']['font_size'] = 87
        studio.write(self.config, settings)
        self.assertEqual(self.artifact_state(), 'settings_changed_approval_invalid')

    def test_legacy_changed_artifact_is_not_revalidated_by_migration(self):
        self.approved_artifact(legacy=True)
        settings = studio.read(self.config)
        settings['pipeline']['captions']['font_size'] += 1
        studio.write(self.config, settings)
        self.set('pipeline.captions.cpu_threads', 7)
        self.assertEqual(self.artifact_state(), 'settings_changed_approval_invalid')
        self.assertNotIn('settings_digest_version', studio.info(self.project)[2]['artifacts'][0])

    def test_explicit_audit_only_metadata_not_effective_but_user_values_are_bound(self):
        settings = studio.read(self.config)
        settings['confirmed_choices']['pipeline.captions.font_size'] = {'value': 86, 'evidence': 'before', 'at': 'old'}
        baseline = settings_digest(settings)
        changed = copy.deepcopy(settings)
        changed['confirmed_choices']['pipeline.captions.font_size'].update(evidence='later', at='new', preference_id='new')
        changed['audit_log'] = [{'event': 'local diagnostic'}]
        changed['pipeline']['residual-check'] = {'output_dir': '/temporary/review', 'cpu_threads': 8}
        self.assertEqual(settings_digest(changed), baseline)
        changed['confirmed_choices']['pipeline.captions.font_size']['value'] = 90
        self.assertNotEqual(settings_digest(changed), baseline)
        for key in ('source', 'model', 'font_file', 'background'):
            changed = copy.deepcopy(settings)
            changed['pipeline']['captions'][key] = '/new/content'
            self.assertNotEqual(settings_digest(changed), baseline)

    def test_legacy_and_new_records_read_and_sources_still_checked(self):
        self.authorize(legacy=True)
        self.assertEqual(self.errors(), [])
        self.set('pipeline.captions.cpu_threads', 9)
        self.source.write_bytes(b'changed synthetic source')
        self.assertTrue(any('original source' in item for item in self.errors()))

    def test_parameter_normalization_is_deliberate_not_blanket_coercion(self):
        self.assertEqual(normalize_setting_value('font_size', '86'), 86)
        self.assertEqual(normalize_setting_value('background_speed', '25.0'), 25)
        self.assertEqual(normalize_setting_value('fps', '60/2'), '30')
        self.assertEqual(normalize_setting_value('mask_shape', 'rounded-square'), 'rounded_square')
        self.assertFalse(normalize_setting_value('single_pass', 'false'))
        self.assertEqual(normalize_setting_value('font_name', '086'), '086')
        self.assertEqual(stage_settings_digest({'font_size': 86, 'output_dir': '/a'}),
                         stage_settings_digest({'font_size': '86', 'output_dir': '/b'}))
        for key, value in [('font_size', 86.5), ('font_size', True), ('fps', 0), ('fps', '1/0'), ('single_pass', 'maybe')]:
            with self.assertRaises(ValueError):
                normalize_setting_value(key, value)


if __name__ == '__main__':
    unittest.main()
