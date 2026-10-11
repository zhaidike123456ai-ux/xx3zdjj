"""Synthetic file/schema tests, never UI compatibility claims or live writes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import jianying_adapter as ja
from stage_gate import CHECKS, validate_report


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.timeline=self.root/'timeline.json';self.report=self.root/'approval.json'
        for name in ['source.mp4','background.mp4','preview.mp4']:(self.root/name).write_bytes(name.encode())
        (self.root/'captions.ass').write_text('[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.10,0:00:01.00,Default,,0,0,0,,你好\nDialogue: 0,0:00:01.00,0:00:01.90,Default,,0,0,0,,世界',encoding='utf-8')
        (self.root/'evidence.txt').write_text('SYNTHETIC evidence; not actual media/user approval', encoding="utf-8")
        def media(name):return {'path':name,'sha256':ja.file_hash(self.root/name),'width':720,'height':1280,'fps':'30/1','frame_count':60}
        self.spec={'schema_version':1,'project_kind':'full','mode':'approved-clean','source':media('source.mp4'),'background':media('background.mp4'),
          'preview':{'path':'preview.mp4','sha256':ja.file_hash(self.root/'preview.mp4')},'captions':{'path':'captions.ass','sha256':ja.file_hash(self.root/'captions.ass'),'format':'ass'},
          'keep_ranges':[{'start_frame':0,'end_frame':25},{'start_frame':25,'end_frame':60}],
          'layout':{'width':1080,'height':1920,'person':{'scale':.57,'center_x':540,'center_y':1520},'mask':{'shape':'circle','center_x':360,'center_y':580,'diameter':720},'caption':{'center_x':540,'center_y':1075,'size':12}}}
        self.refresh()
        def fake_probe(path, executable=None):
            preview=Path(path).name=='preview.mp4'
            return {'streams':[{'codec_type':'video','width':1080 if preview else 720,'height':1920 if preview else 1280,'r_frame_rate':'30/1','avg_frame_rate':'30/1','nb_read_frames':'60','start_time':'0'},{'codec_type':'audio'}]}
        self.patch=patch.object(ja,'probe',side_effect=fake_probe)
        self.audio_patch=patch.object(ja,'audio_signature',return_value='same-synthetic-packets');self.audio_patch.start();self.addCleanup(self.audio_patch.stop)
        self.patch.start();self.addCleanup(self.patch.stop)
    def refresh(self):
        ja.write(self.timeline,self.spec)
        self.gate={'stage':'preview','artifacts':{k:{'sha256':ja.file_hash(self.root/p)} for k,p in [('source','source.mp4'),('ass','captions.ass'),('background','background.mp4'),('preview','preview.mp4'),('timeline','timeline.json')]},
          'checks':{k:{'status':'passed','method':'Synthetic fixture','evidence':['evidence.txt']} for k in CHECKS['preview']},
          'blocking_counts':{'approved_not_executed':0,'known_unfixed':0,'unresolved':0},'user_approval':{'status':'approved','message':'synthetic only','recorded_at':'synthetic','evidence':'evidence.txt'}}
        ja.write(self.report,self.gate)
    def build(self,name='candidate',platform='mac'):
        out=self.root/name;ja.build(self.timeline,self.report,out,'中文显示名称',platform);return out
    def test_full_candidate_bounds_ids_and_frozen_evidence(self):
        a,b=self.build(),self.build('other')
        self.assertEqual(ja.validate(a)['errors'],[])
        ca,cb=ja.read(a/'draft_info.json'),ja.read(b/'draft_info.json')
        self.assertNotEqual(ca['id'],cb['id']);self.assertEqual(ca['duration'],2_000_000)
        self.assertEqual(len(ca['materials']['common_mask']),2)
        self.assertFalse(ja.validate(a)['native_ui_verified'])
        (self.root/'evidence.txt').unlink();self.assertEqual(ja.validate(a)['errors'],[])
    def test_windows_candidate_only(self):
        p=self.build(platform='windows');self.assertTrue((p/'draft_content.json').is_file())
        self.assertFalse(ja.read(p/'generation-manifest.json')['windows_ui_verified'])
    def test_gate_reject_before_output(self):
        self.gate['user_approval']['status']='pending';ja.write(self.report,self.gate)
        with self.assertRaises(ValueError):self.build()
        self.assertFalse((self.root/'candidate').exists())
    def test_input_and_timeline_version_binding(self):
        self.spec['layout']['caption']['size']=999;ja.write(self.timeline,self.spec)
        with self.assertRaises(ValueError):self.build()
    def test_invalid_caption_and_cut_coverage(self):
        self.spec['keep_ranges'][0]['end_frame']=30;self.refresh()
        with self.assertRaises(ValueError):self.build()
        self.spec['keep_ranges'][0]['end_frame']=25
        (self.root/'captions.ass').write_text('[Events]\nDialogue: 0,0:00:01.80,0:00:03.00,Default,,0,0,0,,超界', encoding="utf-8")
        self.spec['captions']['sha256']=ja.file_hash(self.root/'captions.ass');self.refresh()
        with self.assertRaises(ValueError):self.build()
    def test_pipeline_srt_entities_decode_once_ass_literal_preserved(self):
        srt=self.root/'captions.srt'
        srt.write_text('1\n00:00:00,100 --> 00:00:01,900\nA &amp; B &lt; C &amp;lt; literal\n',encoding='utf-8')
        self.spec['captions']={'path':'captions.srt','sha256':ja.file_hash(srt),'format':'srt'}
        ja.write(self.timeline,self.spec)
        self.gate['artifacts']['timeline']['sha256']=ja.file_hash(self.timeline)
        self.gate['artifacts']['ass']['sha256']=ja.file_hash(srt);ja.write(self.report,self.gate)
        candidate=self.build();content=ja.read(candidate/'draft_info.json')
        actual=json.loads(content['materials']['texts'][0]['content'])['text']
        self.assertEqual(actual,'A & B < C &lt; literal')
        self.assertEqual(ja.validate(candidate)['errors'],[])
        ass=self.root/'literal.ass'
        ass.write_text('[Events]\nDialogue: 0,0:00:00.10,0:00:01.90,Default,,0,0,0,,A &amp; B &lt; literal',encoding='utf-8')
        self.assertEqual(ja.caption_rows(ass,'ass')[0]['text'],'A &amp; B &lt; literal')
    def test_approved_audio_mismatch_blocks(self):
        with patch.object(ja,'audio_signature',side_effect=['source','different-preview']):
            with self.assertRaisesRegex(ValueError,'audio packets differ'):self.build()
    def test_cfr_metadata_mismatch(self):
        with patch.object(ja,'probe',return_value={'streams':[{'codec_type':'video','width':720,'height':1280,'r_frame_rate':'29/1','avg_frame_rate':'29/1','nb_read_frames':'60'}]}):
            with self.assertRaises(ValueError):self.build()
    def test_duplicate_output_and_unique_install(self):
        p=self.build();before=ja.tree_hashes(p)
        with self.assertRaises(ValueError):self.build()
        self.assertEqual(before,ja.tree_hashes(p))
        root=self.root/'fake-profile';root.mkdir();(root/'root_meta_info.json').write_bytes(b'unchanged global index')
        result=ja.install(p,root);dest=Path(result['path']);self.assertEqual(ja.validate(dest)['errors'],[])
        self.assertEqual((root/'root_meta_info.json').read_bytes(),b'unchanged global index')
        before=ja.tree_hashes(dest)
        with self.assertRaises(ValueError):ja.install(p,root)
        self.assertEqual(before,ja.tree_hashes(dest))
    def test_snapshot_preserves_opaque_timelines_and_excludes_font(self):
        p=self.root/'saved-draft';(p/'Timelines'/'random').mkdir(parents=True);(p/'Resources').mkdir()
        (p/'draft_info.json').write_bytes(b'\x00opaque not JSON\xff');(p/'Timelines'/'random'/'draft_info.json').write_bytes(b'ciphertext')
        (p/'Resources'/'font.otf').write_bytes(b'font must not distribute');(p/'Resources'/'media.mp4').write_bytes(b'media')
        out=self.root/'snapshot';result=ja.snapshot(p,out,True)
        self.assertEqual((out/'draft_info.json').read_bytes(),b'\x00opaque not JSON\xff')
        self.assertEqual((out/'Timelines'/'random'/'draft_info.json').read_bytes(),b'ciphertext')
        self.assertFalse((out/'Resources'/'font.otf').exists());self.assertEqual(result['cross_device'],'unverified')
        with self.assertRaises(ValueError):ja.snapshot(p,out,True)
    def test_pilot_not_formal_install(self):
        self.spec['project_kind']='pilot';self.refresh();p=self.build();root=self.root/'fake';root.mkdir()
        with self.assertRaises(ValueError):ja.install(p,root)
    def test_static_corruption_detected(self):
        p=self.build();c=ja.read(p/'draft_info.json');c['tracks'][1]['segments'][0]['clip']['scale']['x']=2;ja.write(p/'draft_info.json',c)
        self.assertTrue(ja.validate(p)['errors'])
    def test_original_ranges_not_claimed(self):
        self.spec['mode']='original-ranges';self.refresh()
        with self.assertRaisesRegex(ValueError,'not supported'):self.build()
    def test_native_gate_rejects_pilot_and_unverified_ui(self):
        p=self.build();m=ja.read(p/'generation-manifest.json')
        report=copy.deepcopy(self.gate);report['stage']='jianying-project';report['project_kind']='pilot'
        report['checks']={k:{'status':'passed','method':'Fixture','evidence':['evidence.txt']} for k in CHECKS['jianying-project']}
        ja.write(self.report,report)
        self.assertTrue(validate_report(self.report,'jianying-project',{}))
        report['project_kind']='full';report['native_verification']={'opened_full':True,'editability':True,'saved_reopened':True,'native_export':False,'os':'fixture','app_version':'fixture'}
        ja.write(self.report,report);self.assertTrue(validate_report(self.report,'jianying-project',{}))
    def test_selected_ffprobe_environment_and_explicit_priority(self):
        payload=json.dumps({'streams':[{'codec_type':'audio'}],'packets':[{'data_hash':'fixture'}]})
        # Stop this fixture's probe replacement to exercise actual dispatch only.
        with patch.dict(ja.os.environ,{'XX3ZDJJ_FFPROBE':'selected-ffprobe'}), patch.object(ja.shutil,'which',return_value='path-ffprobe'), patch.object(ja.subprocess,'check_output',return_value=payload) as command:
            self.patch.stop()
            try:
                ja.probe('fixture');self.assertEqual(command.call_args.args[0][0],'selected-ffprobe')
                ja.probe('fixture','explicit-ffprobe');self.assertEqual(command.call_args.args[0][0],'explicit-ffprobe')
                self.audio_patch.stop()
                try:
                    ja.audio_signature('fixture');self.assertEqual(command.call_args.args[0][0],'selected-ffprobe')
                    ja.audio_signature('fixture','explicit-ffprobe');self.assertEqual(command.call_args.args[0][0],'explicit-ffprobe')
                finally:self.audio_patch.start()
            finally:self.patch.start()
    def test_discover_explicit_root_does_not_write(self):
        root=self.root/'override';root.mkdir();before=ja.tree_hashes(root)
        result=ja.discover('mac',draft_root=root);self.assertEqual(before,ja.tree_hashes(root));self.assertFalse(result['writes_performed'])

if __name__=='__main__':unittest.main()
