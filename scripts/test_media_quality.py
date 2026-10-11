"""Synthetic tests; no private footage, no fabricated listening claims."""
import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from run_pipeline import (align_caption_words, ass_escape, ass_time, caption_chunks,
                          cached_recognition, recognition_key, sha256)
from stage_gate import CHECKS


class TextQualityTests(unittest.TestCase):
    def test_missing_script_character_blocks(self):
        rows, report=align_caption_words(["我发现很多人"],[{"word":"我发现人","start":.1,"end":1}])
        self.assertEqual(report["status"],"blocked")
        self.assertEqual([x["character"] for x in report["unmatched_script"]],["很","多"])
        self.assertFalse(rows)

    def test_omitted_spoken_word_blocks(self):
        rows, report=align_caption_words(["我发现"],[{"word":"我我发现","start":.1,"end":1}])
        self.assertEqual(report["status"],"blocked")
        self.assertTrue(report["unmatched_audio"])

    def test_word_timestamps_are_not_interpolated(self):
        rows, report=align_caption_words(["远景","中景"],[{"word":"远景中景","start":.1,"end":1}])
        self.assertEqual(report["word_overlaps"],1)
        self.assertEqual(report["status"],"blocked")
        self.assertEqual(rows[0]["word_end"],1)
        self.assertEqual(rows[1]["word_start"],.1)

    def test_complete_matching_preserves_negation(self):
        words=[{"word":"不一定","start":.123,"end":.8},{"word":"在工具","start":.81,"end":1.4}]
        rows,report=align_caption_words(["不一定在工具"],words)
        self.assertEqual(report["status"],"machine_matched")
        self.assertEqual(rows[0]["word_start"],.123)
        self.assertEqual(rows[0]["word_end"],1.4)

    def test_semantic_long_line_not_blindly_split(self):
        text="不是先堆一大串复杂词而是先想清楚"
        self.assertEqual(caption_chunks([text],11),[text])
        self.assertEqual(caption_chunks(["远景，中景。"],11),["远景","中景。"])

    def test_export_precision_and_escaping(self):
        self.assertEqual(ass_time(.123),"0:00:00.13")
        self.assertEqual(html.escape("A&B<词>",quote=False),"A&amp;B&lt;词&gt;")
        self.assertIn("\\{",ass_escape("{x}\\N"))

    def test_cache_model_and_settings_mismatch_blocks(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("XX3_TEST_ROOT")) as tmp:
            root=Path(tmp); source=root/"source.bin"; source.write_bytes(b"fixture")
            model=root/"model"; model.mkdir(); (model/"config.json").write_text('{}')
            args=argparse.Namespace(model=str(model),cpu_threads=4)
            original=recognition_key(source,args)
            cache=root/"transcript.json"; cache.write_text(json.dumps({"cache_key":original,"segments":[]}))
            self.assertEqual(cached_recognition(source,source,cache,args)["segments"],[])
            (model/"config.json").write_text('{"changed":true}')
            with self.assertRaises(SystemExit): cached_recognition(source,source,cache,args)
            (model/"config.json").write_text('{}'); args.cpu_threads=8
            with self.assertRaises(SystemExit): cached_recognition(source,source,cache,args)
            args.cpu_threads=4; source.write_bytes(b"different")
            with self.assertRaises(SystemExit): cached_recognition(source,source,cache,args)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"FFmpeg required")
class MediaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get("XX3_TEST_ROOT")); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/"source.mp4"
        subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","testsrc2=s=64x96:r=24:d=3",
                        "-f","lavfi","-i","sine=frequency=500:sample_rate=48000:duration=3",
                        "-shortest","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac",str(self.source)],check=True,capture_output=True)
        from PIL import Image
        bg=Image.new("RGB",(64,96)); bg.putdata([(20+3*x,20+3*x,20+3*x) for y in range(96) for x in range(64)])
        self.background=self.root/"background.png"; bg.save(self.background)
        self.ass=self.root/"captions.ass"
        self.ass.write_text('[Script Info]\nScriptType: v4.00+\nPlayResX: 64\nPlayResY: 96\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Main,Helvetica,6,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.20,0:00:02.80,Main,,0,0,0,,{\\pos(32,48)}test\n')
        font_candidates=[Path(os.environ.get("XX3_TEST_FONT","/System/Library/Fonts/Helvetica.ttc")),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
        self.font=next((p for p in font_candidates if p.is_file()),None)
        if not self.font: self.skipTest("provide XX3_TEST_FONT with an installed font")

    def gate(self,stage,artifacts):
        evidence=self.root/'evidence.txt'; evidence.write_text('synthetic approval fixture, not user or acoustic acceptance')
        report=self.root/(stage+'.json')
        report.write_text(json.dumps({"stage":stage,"artifacts":{k:{"sha256":sha256(v)} for k,v in artifacts.items()},
                                     "checks":{k:{"status":"passed","method":"synthetic gate fixture","evidence":[str(evidence)]} for k in CHECKS[stage]},
                                     "blocking_counts":{"approved_not_executed":0,"known_unfixed":0,"unresolved":0},
                                     "user_approval":{"status":"approved","message":"synthetic test","recorded_at":"fixture","evidence":str(evidence)}}))
        return report

    def cli(self,*args):
        return subprocess.run([sys.executable,str(Path(__file__).with_name('run_pipeline.py')),*map(str,args)],capture_output=True,text=True)

    def render(self,shape='circle',muxer=None):
        output=self.root/(shape+'.mp4'); gate=self.gate('captions',{'source':self.source,'ass':self.ass})
        result=self.cli('preview','--source',self.source,'--background',self.background,'--ass',self.ass,
                        '--font-file',self.font,'--approval-report',gate,'--output',output,'--mask-shape',shape,
                        '--subject-crop-y',0,'--canvas-width',64,'--canvas-height',96,'--mask-center-x',32,
                        '--mask-center-y',74,'--mask-diameter',16,'--corner-radius',3,'--background-motion','right',
                        '--background-speed',25,'--crf',0,'--preset','ultrafast',*(['--muxer-bin',muxer] if muxer else []))
        self.assertEqual(result.returncode,0,result.stderr+result.stdout+(output.with_suffix('.validation.json').read_text() if output.with_suffix('.validation.json').is_file() else ''))
        return output,json.loads(output.with_suffix('.validation.json').read_text())

    def test_explicit_muxer_keeps_original_packets(self):
        muxer=os.environ.get('XX3_TEST_MUXER')
        if not muxer: self.skipTest('set XX3_TEST_MUXER to test an explicit stream-copy muxer')
        output,report=self.render(muxer=muxer)
        self.assertEqual(report['audio_packet_identity']['status'],'passed')
        self.assertEqual(report['spec_status'],'passed')

    def test_both_mask_shapes_source_fps_and_audio_copy(self):
        for shape in ('circle','rounded_square'):
            output,report=self.render(shape)
            self.assertEqual(report['fps'],'24/1'); self.assertEqual(report['spec_status'],'passed')
            def packets(path):
                return json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_packets','-show_data_hash','sha256','-of','json',str(path)],check=True,capture_output=True,text=True).stdout)['packets']
            a,b=packets(self.source),packets(output)
            self.assertEqual([{k:x.get(k) for k in ('pts','dts','duration','size','data_hash')} for x in a],
                             [{k:x.get(k) for k in ('pts','dts','duration','size','data_hash')} for x in b])

    def test_right_motion_wrap_has_no_blank_and_expected_direction(self):
        output,report=self.render()
        raw=subprocess.run(['ffmpeg','-v','error','-i',str(output),'-vf','crop=64:20:0:0,format=gray','-f','rawvideo','-'],check=True,capture_output=True).stdout
        frames=[raw[i:i+1280] for i in range(0,len(raw),1280)]
        self.assertEqual(len(frames),72)
        base=list(frames[0][:64])
        self.assertGreater(sum(base)/64,50)
        for index in (12,60,61,62,71):
            row=list(frames[index][:64]); shift=round(index/24*25)%64
            # Pixel grid/filter rounding may differ by one pixel; direction must agree.
            errors=[]
            for offset in (-1,0,1):
                expected=[base[(x-shift-offset)%64] for x in range(64)]
                errors.append(sum(abs(a-b) for a,b in zip(row,expected))/64)
            self.assertLess(min(errors),8,(index,min(errors)))
            self.assertGreater(sum(row)/64,50)

    def test_low_coverage_blocks_before_srt_export(self):
        script=self.root/'script.txt'; script.write_text('hello missing')
        transcript=self.root/'transcript.json'; transcript.write_text(json.dumps({'source_sha256':sha256(self.source),'segments':[{'words':[{'word':'hello','start':.2,'end':1}]}]}))
        out=self.root/'caption_output'; gate=self.gate('rough-cut',{'source':self.source})
        result=self.cli('captions','--source',self.source,'--script',script,'--transcript',transcript,
                        '--output-dir',out,'--font-name','Helvetica','--font-file',self.font,'--approval-report',gate)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertFalse((out/'captions.srt').exists())
        self.assertTrue(json.loads((out/'caption-validation.json').read_text())['unmatched_script'])

    def test_project_config_explicit_cli_precedence(self):
        script=self.root/'script.txt'; script.write_text('hello')
        transcript=self.root/'transcript.json'; transcript.write_text(json.dumps({'source_sha256':sha256(self.source),'segments':[{'words':[{'word':'hello','start':.123,'end':1.4}]}]}))
        config=self.root/'settings.json'; config.write_text(json.dumps({'pipeline':{'captions':{'pos_x':500,'pos_y':1075,'font_size':20,'max_chars':11}}}))
        out=self.root/'caption_config'; gate=self.gate('rough-cut',{'source':self.source})
        result=self.cli('captions','--source',self.source,'--script',script,'--transcript',transcript,
                        '--output-dir',out,'--font-name','Helvetica','--font-file',self.font,'--approval-report',gate,
                        '--project-config',config,'--pos-x',540)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertIn('\\pos(540,1075)',(out/'captions.ass').read_text(encoding='utf-8-sig'))
        self.assertIn('0:00:00.13',(out/'captions.ass').read_text(encoding='utf-8-sig'))


if __name__=='__main__': unittest.main()
