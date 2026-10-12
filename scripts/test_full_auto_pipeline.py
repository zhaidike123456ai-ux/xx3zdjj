"""Synthetic media plumbing with machine-only review fixtures; no listening capability."""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import test_analysis_to_captions as fixtures
import run_pipeline as pipeline
import jianying_adapter as adapter
from stage_gate import CHECKS, validate_report
from workflow_mode import create_authorization


@unittest.skipUnless(fixtures.FFMPEG and fixtures.FFPROBE and fixtures.FONT,'media tools/font required')
class FullAutoPipelineTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.AnalysisToCaptionsTests('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.root=self.h.root
        self.evidence=self.root/'synthetic_ai_review.txt'
        self.evidence.write_text('SYNTHETIC machine review fixture for timing, coverage and provenance; no listening performed.',encoding='utf-8')
        self.authorization_message=self.root/'synthetic_user_authorization.txt'
        self.authorization_message.write_text('SYNTHETIC user selected full_auto and these settings; not real user approval.',encoding='utf-8')
        self.background=Path(__file__).resolve().parent.parent/'assets/default-background.jpg'
        self.settings={'workflow':{'mode':'full_auto','state':'active','run_id':'synthetic_run','revision':1},
            'pipeline':{'analyze':{'retake_policy':'none'},'rough-cut':{},
                'captions':{'font_name':'Helvetica','font_file':fixtures.FONT,'font_size':30,'canvas_width':320,'canvas_height':480,'pos_x':160,'pos_y':240},
                'preview':{'mask_shape':'circle','background':str(self.background),'background_motion':'static','background_speed':0.0,
                           'canvas_width':320,'canvas_height':480,'mask_center_x':160,'mask_center_y':360,'mask_diameter':120}}}
        self.config=self.root/'settings.json';fixtures.write_json(self.config,self.settings)
        self.choices={'retake_policy':'none','font_name':'Helvetica','mask_shape':'circle',
            'background':{'kind':'default','path':str(self.background),'sha256':pipeline.sha256(self.background)},
            'background_motion':'static','delivery':'mp4_and_jianying'}
        self.settings['confirmed_choices']=copy.deepcopy(self.choices)
        fixtures.write_json(self.config,self.settings)
        auth=create_authorization(self.settings,[self.h.source],self.choices,self.authorization_message,
            message='SYNTHETIC one-time full_auto authorization',recorded_at='synthetic',settings_path=self.config)
        self.auth=self.root/'authorization.json';fixtures.write_json(self.auth,auth)
        self.settings['workflow']['authorization']={'path':str(self.auth),'sha256':pipeline.sha256(self.auth)}
        fixtures.write_json(self.config,self.settings)
        self.workflow={'mode':'full_auto','settings':{'path':str(self.config)},
            'authorization':{'path':str(self.auth),'sha256':pipeline.sha256(self.auth)}}

    def gate(self,stage,inputs,path,**extra):
        report={'stage':stage,'workflow':copy.deepcopy(self.workflow),
            'artifacts':{k:{'sha256':pipeline.sha256(v)} for k,v in inputs.items()},
            'checks':{k:{'status':'passed','method':'SYNTHETIC fixture only','evidence':[str(self.evidence)]} for k in CHECKS[stage]},
            'blocking_counts':{'approved_not_executed':0,'known_unfixed':0,'unresolved':0},**extra}
        if stage in ('captions','preview'):
            mapping=self.h.rough/'edit-map.json'
            report['source_provenance']={'edit_map':{'path':str(mapping),'sha256':pipeline.sha256(mapping)}}
        report['ai_review']={'status':'passed','reviewer_id':'synthetic_independent_reviewer','method':'machine_evidence_review',
            'evidence':[{'kind':'machine_verification','path':str(self.evidence),'sha256':pipeline.sha256(self.evidence)}],
            'artifacts':copy.deepcopy(report['artifacts']),'covered_checks':list(CHECKS[stage])}
        fixtures.write_json(path,report);return report

    def prepare_rough(self):
        self.h.analyze()
        self.plan=self.root/'plan_gate.json'
        self.gate('analysis',{'source':self.h.source},self.plan,
                  execution={'fps':None,'confirmed_delete':[],'approve_candidate':[],'decision_file_sha256':None})
        code,text=self.h.invoke_main('rough-cut','--source',self.h.source,'--analysis-dir',self.h.analysis,
            '--output-dir',self.h.rough,'--preset','ultrafast','--project-config',self.config,'--decision-report',self.plan)
        self.assertEqual(code,0,text)
        self.h.media=self.h.rough/'rough_cut_no_captions.mp4'
        def decode(decoder,window):return self.h.mocked_decoder(decoder,window)
        with mock.patch.object(pipeline.OpeningDecoder,'__call__',decode):
            code,text=self.h.invoke_main('residual-check','--source',self.h.media,'--output-dir',self.h.residual,'--model','synthetic_no_model')
        self.assertEqual(code,0,text)
        self.h.review=fixtures.read_json(self.h.residual/'review-report.json')
        old,resolutions,_=self.h.protocol_evidence()
        for item in resolutions['alerts']+resolutions['check_resolutions']:
            item['reviewer']={'kind':'agent','method':'machine_evidence_review','recorded_at':'synthetic',
                              'quote':'Synthetic fixture: machine timing, coverage and lineage records checked.'}
            item['assessment']='Synthetic protocol fixture: machine evidence accounts for this alert or check; no listening claim.'
            item['evidence']=[{'kind':'machine_verification','path':str(self.evidence),'sha256':pipeline.sha256(self.evidence)}]
        fixtures.write_json(self.h.resolutions,resolutions)
        residual=old['residual_review'];residual['resolutions']['sha256']=pipeline.sha256(self.h.resolutions)
        self.gate('rough-cut',{'source':self.h.media},self.h.gate,residual_review=residual)

    def test_full_auto_to_native_project_without_listening_or_stage_user_approvals(self):
        self.prepare_rough()
        captions=self.root/'captions'
        code,text=self.h.invoke_main('captions','--source',self.h.media,'--script',self.h.script,
            '--transcript',self.h.caption_transcript,'--output-dir',captions,'--approval-report',self.h.gate,
            '--font-name','Helvetica','--font-file',fixtures.FONT,'--project-config',self.config)
        self.assertEqual(code,0,text);self.assertTrue((captions/'captions.srt').is_file())
        caption_gate=self.root/'caption_gate.json';ass=captions/'captions.ass'
        self.gate('captions',{'source':self.h.media,'ass':ass},caption_gate)
        preview=self.root/'preview.mp4'
        args=['preview','--source',self.h.media,'--background',self.background,'--ass',ass,
            '--font-file',fixtures.FONT,'--approval-report',caption_gate,'--output',preview,
            '--mask-shape','circle','--subject-crop-y','0','--preset','ultrafast','--project-config',self.config]
        muxer=os.environ.get('XX3_TEST_MUXER')
        if muxer:args+=['--muxer-bin',muxer]
        code,text=self.h.invoke_main(*args);self.assertEqual(code,0,text)
        background=self.root/'background.mp4'
        subprocess.run([fixtures.FFMPEG,'-y','-v','error','-loop','1','-framerate','24','-i',str(self.background),
            '-vf','scale=320:480:force_original_aspect_ratio=increase,crop=320:480,setsar=1',
            '-frames:v','96','-an','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(background)],check=True,capture_output=True)
        def media(path,width,height):return {'path':str(path),'sha256':pipeline.sha256(path),'width':width,'height':height,'fps':'24/1','frame_count':96}
        spec={'schema_version':1,'project_kind':'full','mode':'approved-clean',
            'source':media(self.h.media,64,96),'background':media(background,320,480),
            'preview':{'path':str(preview),'sha256':pipeline.sha256(preview)},
            'captions':{'path':str(ass),'sha256':pipeline.sha256(ass),'format':'ass'},
            'keep_ranges':[{'start_frame':0,'end_frame':96}],
            'layout':{'width':320,'height':480,'person':{'scale':.5,'center_x':160,'center_y':360},
                      'mask':{'shape':'circle','center_x':32,'center_y':48,'diameter':64},
                      'caption':{'center_x':160,'center_y':240,'size':12}}}
        timeline=self.root/'timeline.json';fixtures.write_json(timeline,spec)
        preview_gate=self.root/'preview_gate.json'
        self.gate('preview',{'source':self.h.media,'ass':ass,'preview':preview,'background':background,'timeline':timeline},preview_gate)
        project=self.root/'native_project'
        adapter.build(timeline,preview_gate,project,'Synthetic full auto','mac',ffprobe=fixtures.FFPROBE,project_config=self.config)
        result=adapter.validate(project)
        self.assertEqual(result['errors'],[]);self.assertEqual(result['status'],'STATIC_VALIDATED_NATIVE_UI_PENDING')
        profile=self.root/'synthetic_draft_root';profile.mkdir()
        installed=adapter.install(project,profile)
        self.assertEqual(installed['status'],'INSTALLED_NATIVE_UI_PENDING')
        self.assertFalse(installed['existing_projects_changed'])
        frozen=fixtures.read_json(project/'approval-report.json')
        self.assertNotIn('user_approval',frozen);self.assertTrue(frozen['workflow']['frozen_snapshot'])
        # Archived evidence supports offline checks after live run settings disappear.
        self.config.unlink();self.auth.unlink();self.authorization_message.unlink();self.evidence.unlink()
        (self.h.rough/'edit-map.json').unlink()
        self.assertEqual(adapter.validate(project)['errors'],[])
        self.assertTrue(validate_report(project/'approval-report.json','preview',{'source':self.h.media}))
        self.assertEqual(pipeline.sha256(self.h.source),self.h.source_hash)

    def test_rough_cut_rejects_changed_plan_before_render(self):
        self.h.analyze();plan=self.root/'plan.json'
        self.gate('analysis',{'source':self.h.source},plan,execution={'fps':None,'confirmed_delete':[],'approve_candidate':[],'decision_file_sha256':None})
        code,text=self.h.invoke_main('rough-cut','--source',self.h.source,'--analysis-dir',self.h.analysis,
            '--output-dir',self.h.rough,'--confirmed-delete','0:0.1:changed after review',
            '--project-config',self.config,'--decision-report',plan)
        self.assertEqual(code,2,text);self.assertFalse(self.h.rough.exists())

    def test_full_auto_without_plan_or_mode_selection_cannot_render(self):
        self.h.analyze()
        args=['rough-cut','--source',self.h.source,'--analysis-dir',self.h.analysis,'--output-dir',self.h.rough,'--project-config',self.config]
        code,text=self.h.invoke_main(*args);self.assertEqual(code,2,text)
        self.settings['workflow']={'mode':'unselected','state':'pending'};fixtures.write_json(self.config,self.settings)
        code,text=self.h.invoke_main(*args);self.assertEqual(code,2,text);self.assertFalse(self.h.rough.exists())

    def test_semiauto_does_not_accept_ai_review_as_user_approval(self):
        self.prepare_rough()
        self.settings['workflow']={'mode':'semi_auto','state':'active'};fixtures.write_json(self.config,self.settings)
        errors=validate_report(self.h.gate,'rough-cut',{'source':self.h.media},project_config=self.config)
        self.assertTrue(errors)

    def test_explicit_crop_override_rejected(self):
        import argparse
        config=copy.deepcopy(self.settings)
        config['pipeline']['preview'].update(subject_crop_y=10,corner_radius=48)
        report=self.root/'settings_gate.json';fixtures.write_json(report,{})
        args=argparse.Namespace(stage='preview',subject_crop_y=11,corner_radius=60,font_file=Path(fixtures.FONT))
        errors=pipeline.automatic_execution_errors(args,config,report)
        self.assertTrue(any('subject_crop_y' in error for error in errors))
        self.assertTrue(any('corner_radius' in error for error in errors))

    def test_selected_acoustic_evidence_change_blocks_rough_cut(self):
        import csv
        import argparse
        self.h.analyze()
        evidence=self.root/'bounds.json'
        fixtures.write_json(evidence,{'source_sha256':self.h.source_hash,'status':'verified_acoustic_bounds',
            'previous_word_end':.1,'failed_audio_onset':.3,'last_complete_audio_onset':.6})
        decision=self.root/'decisions.csv'
        with decision.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['candidate_id','delete_start','delete_end','acoustic_evidence'])
            writer.writeheader();writer.writerow({'candidate_id':'R1','delete_start':.2,'delete_end':.5,'acoustic_evidence':evidence.name})
        args=argparse.Namespace(source=self.h.source,decision_file=decision,approve_candidate=['R1'])
        plan=self.root/'acoustic_plan.json'
        self.gate('analysis',pipeline.decision_review_inputs(args),plan,
            execution={'fps':None,'confirmed_delete':[],'approve_candidate':['R1'],'decision_file_sha256':pipeline.sha256(decision)})
        changed=fixtures.read_json(evidence);changed['previous_word_end']=.05;fixtures.write_json(evidence,changed)
        code,text=self.h.invoke_main('rough-cut','--source',self.h.source,'--analysis-dir',self.h.analysis,
            '--output-dir',self.h.rough,'--decision-file',decision,'--approve-candidate','R1',
            '--project-config',self.config,'--decision-report',plan)
        self.assertEqual(code,2,text);self.assertIn('acoustic_0000',text);self.assertFalse(self.h.rough.exists())

    def test_full_auto_rejects_ai_review_with_unresolved_alert(self):
        self.prepare_rough()
        resolutions=fixtures.read_json(self.h.resolutions);resolutions['alerts']=[]
        fixtures.write_json(self.h.resolutions,resolutions)
        gate=fixtures.read_json(self.h.gate);gate['residual_review']['resolutions']['sha256']=pipeline.sha256(self.h.resolutions)
        fixtures.write_json(self.h.gate,gate)
        self.assertTrue(validate_report(self.h.gate,'rough-cut',{'source':self.h.media},project_config=self.config))


if __name__=='__main__':unittest.main()
