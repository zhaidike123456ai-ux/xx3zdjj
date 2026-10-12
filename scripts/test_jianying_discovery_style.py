"""Synthetic config/project tests only: no native UI, fonts, live roots or audio use."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import jianying_adapter as adapter
import test_jianying_adapter as legacy_tests


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.local=self.root/'LOCALAPPDATA'
        self.config_dir=self.local/'JianyingPro'/'User Data'/'Config'
        self.config_dir.mkdir(parents=True)
        self.default=self.local/'JianyingPro'/'User Data'/'Projects'/'com.lveditor.draft'
        self.default.mkdir(parents=True)
        (self.default/'root_meta_info.json').write_text('{}',encoding='utf-8')
        self.custom=self.root/'custom_draft_root'
        self.custom.mkdir();(self.custom/'root_meta_info.json').write_text('{}',encoding='utf-8')
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(self.local)})
        self.env.start();self.addCleanup(self.env.stop)

    def write(self,path,data):
        path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def test_known_utf8_json_custom_root_precedes_default_without_writes(self):
        config=self.config_dir/'settings.json'
        self.write(config,{'editor':{'draft_root_path':str(self.custom)},'note':'中文配置'})
        before=adapter.tree_hashes(self.root)
        result=adapter.discover('windows')
        self.assertEqual(result['draft_roots'][0]['path'],str(self.custom.resolve()))
        self.assertEqual(result['draft_roots'][0]['config_field'],'editor.draft_root_path')
        self.assertEqual(result['draft_roots'][0]['config_file'],str(config.resolve()))
        self.assertEqual(adapter.tree_hashes(self.root),before)
        self.assertFalse(result['writes_performed'])
        self.assertFalse(result['windows_ui_verified'])

    def test_explicit_json_has_priority_over_known_and_default(self):
        third=self.root/'another_root';third.mkdir();(third/'root_meta_info.json').write_text('{}',encoding='utf-8')
        self.write(self.config_dir/'known.json',{'draft_path':str(third)})
        explicit=self.root/'explicit.json';self.write(explicit,{'draftSavePath':str(self.custom)})
        result=adapter.discover('windows',config_file=explicit)
        self.assertEqual(result['draft_roots'][0]['path'],str(self.custom.resolve()))
        self.assertEqual(result['draft_roots'][0]['source'],'explicit configuration field')
        self.assertEqual(result['draft_roots'][1]['path'],str(third.resolve()))

    def test_ini_relative_and_environment_config_fields(self):
        config=self.root/'actual.ini'
        config.write_text('[editor]\ndraft_save_path=custom_draft_root\n',encoding='utf-8')
        result=adapter.discover('windows',config_file=config)
        self.assertEqual(result['draft_roots'][0]['path'],str(self.custom.resolve()))
        self.write(self.root/'env.json',{'draft_root_path':'%LOCALAPPDATA%/JianyingPro/User Data/Projects/com.lveditor.draft'})
        result=adapter.discover('windows',config_file=self.root/'env.json')
        self.assertEqual(result['draft_roots'][0]['path'],str(self.default.resolve()))

    def test_quoted_camel_case_ini_paths_are_actual_fields(self):
        config=self.root/'actual.ini'
        config.write_text('[editor]\ndraftSavePath="'+str(self.custom)+'"\n',encoding='utf-8')
        result=adapter.discover('windows',config_file=config)
        self.assertEqual(result['draft_roots'][0]['path'],str(self.custom.resolve()))
        self.assertEqual(result['draft_roots'][0]['config_field'],'editor.draftSavePath')

    def test_utf16_ini_and_legacy_ansi_ini_can_be_read_bounded(self):
        config=self.root/'actual.ini'
        config.write_text('[editor]\ndraft_path='+str(self.custom)+'\n;中文注释\n',encoding='utf-16')
        self.assertEqual(adapter.discover('windows',config_file=config)['draft_roots'][0]['path'],str(self.custom.resolve()))
        config.write_text('[editor]\ndraft_path='+str(self.custom)+'\n;中文注释\n',encoding='gb18030')
        self.assertEqual(adapter.discover('windows',config_file=config)['draft_roots'][0]['path'],str(self.custom.resolve()))

    def test_unmarked_missing_and_oversized_paths_are_not_guessed_or_created(self):
        unmarked=self.root/'unmarked';unmarked.mkdir()
        explicit=self.root/'explicit.json'
        self.write(explicit,{'draft_path':str(unmarked),'draft_root_path':str(self.root/'missing')})
        result=adapter.discover('windows',config_file=explicit)
        self.assertEqual([x['path'] for x in result['draft_roots']],[str(self.default.resolve())])
        self.assertEqual(len(result['config_diagnostics']),2)
        self.assertFalse((self.root/'missing').exists())
        explicit.write_bytes(b' '* (adapter.MAX_CONFIG_BYTES+1))
        result=adapter.discover('windows',config_file=explicit)
        self.assertIn('bounded discovery size',result['config_diagnostics'][0]['reason'])

    def test_unknown_fields_are_ignored_and_same_root_is_deduplicated(self):
        config=self.root/'explicit.json'
        self.write(config,{'output_path':str(self.custom),'draft_path':str(self.default)})
        result=adapter.discover('windows',config_file=config)
        self.assertEqual(len(result['draft_roots']),1)
        self.assertEqual(result['draft_roots'][0]['path'],str(self.default.resolve()))

    def test_cli_config_file_dispatch(self):
        config=self.root/'explicit.json';self.write(config,{'draft_path':str(self.custom)})
        capture=io.StringIO()
        with redirect_stdout(capture):
            code=adapter.main(['discover','--platform','windows','--config-file',str(config)])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(capture.getvalue())['draft_roots'][0]['path'],str(self.custom.resolve()))

    def test_explicit_draft_override_preserves_legacy_route(self):
        unmarked=self.root/'trusted_explicit';unmarked.mkdir()
        result=adapter.discover('mac',draft_root=unmarked)
        self.assertEqual(result['draft_roots'][0]['path'],str(unmarked.resolve()))
        self.assertEqual(result['draft_roots'][0]['source'],'explicit override')

    def test_ffprobe_json_requests_utf8_including_chinese_filename(self):
        sample=json.dumps({'streams':[],'format':{'filename':'中文视频.mp4'}},ensure_ascii=False)
        with patch.object(adapter.subprocess,'check_output',return_value=sample) as command:
            value=adapter.probe('synthetic','explicit-probe')
        self.assertEqual(value['format']['filename'],'中文视频.mp4')
        self.assertEqual(command.call_args.kwargs['encoding'],'utf-8')


class NativeStyleTests(unittest.TestCase):
    def setUp(self):
        self.fixture=legacy_tests.AdapterTests('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root

    def caption_body(self,path):
        manifest=adapter.read(path/'generation-manifest.json')
        content=adapter.read(path/manifest['content_file'])
        return json.loads(content['materials']['texts'][0]['content'])

    def test_legacy_default_shadow_remains_exact_and_unverified(self):
        path=self.fixture.build()
        style=self.caption_body(path)['styles'][0]
        self.assertEqual(style['shadows'],[{'diffuse':.025,'alpha':1.,'distance':5.,
            'content':{'solid':{'color':[0.,0.,0.]}},'angle':-45.}])
        record=adapter.read(path/'generation-manifest.json')['caption_style']
        self.assertEqual(record['shadow_source'],'legacy_default')
        self.assertEqual(record['pixel_equivalence'],'unverified')
        self.assertEqual(adapter.validate(path)['errors'],[])

    def test_explicit_native_shadow_applied_without_invented_correction_factor(self):
        shadow=dict(diffuse=.07,alpha=.65,distance=3.,angle=-30.,color=[.1,.2,.3])
        self.fixture.spec['layout']['caption']['shadow']=shadow;self.fixture.refresh()
        path=self.fixture.build()
        self.assertEqual(self.caption_body(path)['styles'][0]['shadows'],adapter.native_shadows(adapter.normalized_shadow(shadow)))
        manifest=adapter.read(path/'generation-manifest.json')
        self.assertEqual(manifest['caption_style']['shadow']['distance'],3.)
        self.assertEqual(manifest['caption_style']['pixel_equivalence'],'unverified')
        self.assertEqual(adapter.validate(path)['errors'],[])

    def test_disabled_shadow_and_corrupted_native_shadow(self):
        self.fixture.spec['layout']['caption']['shadow']={'enabled':False};self.fixture.refresh()
        path=self.fixture.build()
        self.assertEqual(self.caption_body(path)['styles'][0]['shadows'],[])
        content=adapter.read(path/'draft_info.json')
        body=json.loads(content['materials']['texts'][0]['content'])
        body['styles'][0]['shadows']=[{'alpha':1}]
        content['materials']['texts'][0]['content']=json.dumps(body)
        adapter.write(path/'draft_info.json',content)
        self.assertTrue(any('shadow changed' in x for x in adapter.validate(path)['errors']))

    def profile(self):
        evidence=self.root/'calibration_evidence.json'
        evidence.write_text('SYNTHETIC parameter-calibration fixture, not actual UI proof.',encoding='utf-8')
        return {'id':'synthetic_profile','shadow':{'alpha':.8,'distance':4.},'calibration':{
            'status':'calibrated','platform':'mac','app_version':'fixture-version',
            'font_name':'fixture-font','font_version':'fixture-font-version',
            'evidence':[{'path':str(evidence),'sha256':adapter.file_hash(evidence)}]}},evidence

    def test_profile_parameters_versions_and_evidence_freeze_not_pixel_acceptance(self):
        profile,evidence=self.profile()
        self.fixture.spec['layout']['caption']['style_profile']=profile;self.fixture.refresh()
        path=self.fixture.build()
        record=adapter.read(path/'generation-manifest.json')['caption_style']
        self.assertEqual(record['shadow_source'],'style_profile.shadow')
        self.assertEqual(record['calibration']['status'],'historical_evidence_recorded')
        self.assertEqual(record['calibration']['platform'],'mac')
        self.assertEqual(record['calibration']['font_version'],'fixture-font-version')
        self.assertEqual(record['current_app_font_match'],'unverified')
        self.assertEqual(record['pixel_equivalence'],'unverified')
        evidence.unlink()
        self.assertEqual(adapter.validate(path)['errors'],[])  # Only immutable snapshot is needed.
        snapshot=path/record['evidence_snapshots'][0]['path'];snapshot.write_text('changed',encoding='utf-8')
        self.assertTrue(any('snapshot missing or changed' in x for x in adapter.validate(path)['errors']))

    def test_profile_override_or_platform_change_downgrades_applicability(self):
        profile,_=self.profile()
        self.fixture.spec['layout']['caption'].update(style_profile=profile,shadow={'distance':8.})
        self.fixture.refresh();path=self.fixture.build(platform='windows')
        record=adapter.read(path/'generation-manifest.json')['caption_style']
        self.assertEqual(record['shadow']['distance'],8.)
        self.assertEqual(record['calibration']['status'],'unverified')
        self.assertEqual(len(record['calibration']['reasons']),2)
        self.assertFalse(adapter.validate(path)['native_ui_verified'])

    def test_calibrated_record_missing_versions_or_evidence_is_rejected(self):
        profile,_=self.profile();profile['calibration'].pop('font_version')
        self.fixture.spec['layout']['caption']['style_profile']=profile;self.fixture.refresh()
        with self.assertRaisesRegex(ValueError,'font_version'):self.fixture.build()
        profile['calibration']['font_version']='fixture';profile['calibration']['evidence']=[]
        self.fixture.refresh()
        with self.assertRaisesRegex(ValueError,'hashed evidence'):self.fixture.build()

    def test_candidate_cannot_upgrade_pixel_match_claim_without_evidence(self):
        path=self.fixture.build()
        manifest=adapter.read(path/'generation-manifest.json')
        manifest['caption_style']['pixel_equivalence']='verified'
        adapter.write(path/'generation-manifest.json',manifest)
        self.assertTrue(any('style/calibration record changed' in x for x in adapter.validate(path)['errors']))

    def test_invalid_shadow_values_rejected(self):
        for shadow in ({'alpha':2},{'diffuse':-1},{'distance':float('nan')},
                       {'color':[0,0,2]},{'opacity':.8},{'enabled':'false'}):
            with self.subTest(shadow=shadow),self.assertRaises(ValueError):
                adapter.normalized_shadow(shadow)

    def test_platform_mismatch_install_blocks_but_cross_platform_build_still_allowed(self):
        mac=self.fixture.build('mac_candidate','mac')
        windows=self.fixture.build('windows_candidate','windows')
        profile=self.root/'synthetic_profile_root';profile.mkdir()
        with patch.object(adapter.platform,'system',return_value='Windows'):
            with self.assertRaisesRegex(ValueError,'platform differs'):adapter.install(mac,profile)
            installed=adapter.install(windows,profile)
        destination=Path(installed['path'])
        self.assertTrue((destination/'draft_content.json').is_file())
        self.assertEqual(installed['status'],'INSTALLED_NATIVE_UI_PENDING')
        self.assertFalse(installed['windows_ui_verified'])
        other=self.root/'other_profile';other.mkdir()
        with patch.object(adapter.platform,'system',return_value='Darwin'):
            with self.assertRaisesRegex(ValueError,'platform differs'):adapter.install(windows,other)
            self.assertEqual(adapter.install(mac,other)['status'],'INSTALLED_NATIVE_UI_PENDING')


if __name__=='__main__':unittest.main()
