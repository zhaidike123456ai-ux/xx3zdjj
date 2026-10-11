import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from stage_gate import file_hash


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RoughCutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("XX3_TEST_ROOT"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "fixture.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=64x96:r=24:d=2",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=2", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(self.source),
        ], check=True, capture_output=True)
        self.analysis = self.root / "analysis"
        self.analysis.mkdir()
        (self.analysis / "analysis-manifest.json").write_text(
            json.dumps({"source_sha256": file_hash(self.source)}), encoding="utf-8")
        self.output = self.root / "output"

    def run_cut(self, *extra):
        return subprocess.run([
            sys.executable, str(Path(__file__).with_name("run_pipeline.py")), "rough-cut",
            "--source", str(self.source), "--analysis-dir", str(self.analysis),
            "--output-dir", str(self.output), "--preset", "ultrafast", *extra,
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_preserves_source_fps_and_dimensions(self):
        result = self.run_cut("--confirmed-delete", "0.5:1.0:test")
        self.assertEqual(result.returncode, 0, result.stderr)
        validation = json.loads((self.output / "validation.json").read_text(encoding="utf-8"))
        stream = next(s for s in validation["probe"]["streams"] if s["codec_type"] == "video")
        self.assertEqual((stream["width"], stream["height"]), (64, 96))
        self.assertEqual(stream["r_frame_rate"], "24/1")
        self.assertAlmostEqual(float(validation["probe"]["format"]["duration"]), 1.5, delta=0.05)
        self.assertEqual(validation["full_decode"], "passed")
        self.assertEqual(validation["spec_status"], "passed")
        clips=json.loads((self.output / "cut-listening/manifest.json").read_text())["clips"]
        self.assertEqual(len(clips),3)
        self.assertTrue(all(Path(x["path"]).is_file() for x in clips))
        self.assertEqual(file_hash(self.source),
                         json.loads((self.analysis / "analysis-manifest.json").read_text())["source_sha256"])

    def test_missing_decision_does_not_silently_ignore_approval(self):
        result = self.run_cut("--approve-candidate", "RT1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_invalid_candidate_range_blocks_before_render(self):
        decision = self.root / "decisions.csv"
        with decision.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["candidate_id", "delete_start", "delete_end"])
            writer.writeheader()
            writer.writerow({"candidate_id": "RT1", "delete_start": -1, "delete_end": 1})
        result = self.run_cut("--decision-file", str(decision), "--approve-candidate", "RT1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_changed_source_blocks_stale_cache(self):
        (self.analysis / "analysis-manifest.json").write_text(
            json.dumps({"source_sha256": "wrong hash"}), encoding="utf-8")
        self.assertNotEqual(self.run_cut().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_acoustic_evidence_is_used_and_source_bound(self):
        evidence=self.root/"acoustic.json"
        evidence.write_text(json.dumps({"source_sha256":file_hash(self.source),"status":"verified_acoustic_bounds",
                                       "previous_word_end":.4,"failed_audio_onset":.55,"last_complete_audio_onset":1.1}))
        decision=self.root/"decisions.csv"
        with decision.open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=["candidate_id","candidate_type","delete_start","delete_end","acoustic_evidence"])
            writer.writeheader(); writer.writerow({"candidate_id":"FR1","candidate_type":"short_fragment_or_swallowed_restart",
                                                  "delete_start":.6,"delete_end":1,"acoustic_evidence":str(evidence)})
        result=self.run_cut("--decision-file",str(decision),"--approve-candidate","FR1")
        self.assertEqual(result.returncode,0,result.stderr)
        edit=json.loads((self.output/"edit-map.json").read_text())
        self.assertAlmostEqual(edit["boundary_evidence"][0]["resolved_start"],13/24)

    def test_short_restart_without_evidence_blocks(self):
        decision=self.root/"decisions.csv"
        with decision.open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=["candidate_id","candidate_type","delete_start","delete_end"])
            writer.writeheader(); writer.writerow({"candidate_id":"FR1","candidate_type":"short_fragment_or_swallowed_restart","delete_start":.5,"delete_end":1})
        result=self.run_cut("--decision-file",str(decision),"--approve-candidate","FR1")
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
