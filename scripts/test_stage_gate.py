import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from stage_gate import CHECKS, file_hash, validate_report
from review_state import REQUIRED_CHECKS, full_coverage, make_report
from test_review_state import synthetic_lineage


class StageGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "media.bin"
        self.source.write_bytes(b"synthetic gate test; not a media quality test")
        (self.root / "evidence.txt").write_text("test fixture", encoding="utf-8")
        self.report = self.root / "gate.json"
        self.residual_path = self.root / "residual.json"
        self.residual_data = make_report(self.source, 1.0, {
            key: {"status": "executed", "result": "passed", "method": "synthetic detector fixture",
                  "coverage": full_coverage(1.0)} for key in REQUIRED_CHECKS}, [])
        self.residual_data['source_review_lineage'] = synthetic_lineage(self.root, self.source, 1.0)
        self.residual_path.write_text(json.dumps(self.residual_data), encoding="utf-8")
        self.data = {
            "stage": "rough-cut",
            "residual_review": {"report": {"path": "residual.json", "sha256": file_hash(self.residual_path)}},
            "artifacts": {"source": {"sha256": file_hash(self.source)}},
            "checks": {key: {"status": "passed", "method": "synthetic test",
                              "evidence": ["evidence.txt"]}
                       for key in CHECKS["rough-cut"]},
            "blocking_counts": {"approved_not_executed": 0, "known_unfixed": 0,
                                "unresolved": 0},
            "user_approval": {"status": "approved", "message": "fixture approval",
                              "recorded_at": "fixture time", "evidence": "evidence.txt"},
        }

    def check(self):
        self.report.write_text(json.dumps(self.data), encoding="utf-8")
        return validate_report(self.report, "rough-cut", {"source": self.source})

    def test_valid_record(self):
        self.assertEqual(self.check(), [])

    def test_legacy_without_current_residual_review_blocks(self):
        del self.data["residual_review"]
        self.assertTrue(any("residual-review" in e for e in self.check()))

    def test_zero_counts_cannot_hide_unresolved_review_alert(self):
        self.residual_data["alerts"] = [{"id": "alert-synthetic", "check_id": "repeated_speech",
                                        "start": .2, "end": .4, "review_required": True}]
        self.residual_data["quality_status"] = "review_required"
        self.residual_path.write_text(json.dumps(self.residual_data), encoding="utf-8")
        self.data["residual_review"]["report"]["sha256"] = file_hash(self.residual_path)
        self.assertTrue(any("unresolved review_required" in e for e in self.check()))

    def machine_resolution(self):
        self.residual_data['alerts'] = [{'id': 'synthetic-machine-alert', 'check_id': 'repeated_speech',
                                        'start': .2, 'end': .4, 'review_required': True}]
        self.residual_data['quality_status'] = 'review_required'
        self.residual_data['checks']['repeated_speech']['result'] = 'review_required'
        self.residual_path.write_text(json.dumps(self.residual_data), encoding='utf-8')
        self.data['residual_review']['report']['sha256'] = file_hash(self.residual_path)
        coverage = {'scope': 'alert_window', 'start': .2, 'end': .4}
        (self.root / 'evidence.txt').write_text(json.dumps({
            'schema_version': 2, 'kind': 'machine_verification',
            'source_sha256': file_hash(self.source), 'report_sha256': file_hash(self.residual_path),
            'alert_id': 'synthetic-machine-alert', 'coverage': coverage, 'verification': 'confirmed_benign',
            'observations': [{'method': 'synthetic timing and mapping comparison',
                              'finding': 'SYNTHETIC fixture: the 0.2-0.4 second alert window maps to retained normal repetition; not real speech acceptance.'}]
        }), encoding='utf-8')
        resolution = self.root / 'machine-resolutions.json'
        resolution.write_text(json.dumps({
            'schema_version': 2, 'report_sha256': file_hash(self.residual_path),
            'source_sha256': file_hash(self.source), 'check_resolutions': [], 'alerts': [{
                'alert_id': 'synthetic-machine-alert', 'decision': 'retain',
                'verification': 'confirmed_benign', 'coverage': coverage,
                'assessment': 'Synthetic machine timing comparison; no listening claim.',
                'reviewer': {'kind': 'agent', 'method': 'machine_evidence_review',
                             'recorded_at': 'synthetic time', 'quote': 'Synthetic review fixture.'},
                'evidence': [{'path': 'evidence.txt', 'sha256': file_hash(self.root / 'evidence.txt'),
                              'kind': 'machine_verification'}]}]}), encoding='utf-8')
        self.data['residual_review']['resolutions'] = {'path': resolution.name, 'sha256': file_hash(resolution)}
        return resolution

    def test_semi_auto_machine_resolution_needs_no_listening_capability(self):
        self.machine_resolution()
        self.data['user_approval']['message'] = 'Synthetic stage continuation confirmation, not a listening assertion.'
        self.assertEqual(self.check(), [])

    def test_machine_resolution_evidence_change_still_blocks(self):
        self.machine_resolution()
        (self.root / 'evidence.txt').write_text('changed synthetic evidence', encoding='utf-8')
        self.assertTrue(any('evidence changed' in e for e in self.check()))

    def test_changed_residual_reference_blocks(self):
        self.residual_path.write_text(self.residual_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        self.assertTrue(any("report changed" in e for e in self.check()))

    def test_changed_media(self):
        self.source.write_bytes(b"changed version")
        self.assertTrue(self.check())

    def test_missing_checks(self):
        del self.data["checks"]["G5"]
        self.assertTrue(self.check())

    def test_failure_and_unverified(self):
        for status in ("failed", "unverified", "pending"):
            self.data["checks"]["G4"]["status"] = status
            self.assertTrue(self.check())

    def test_unresolved_or_false_counts(self):
        for value in (1, False, "0", None):
            self.data["blocking_counts"]["unresolved"] = value
            self.assertTrue(self.check())

    def test_no_user_approval(self):
        self.data["user_approval"]["status"] = "pending"
        self.assertTrue(self.check())

    def test_missing_evidence(self):
        (self.root / "evidence.txt").unlink()
        self.assertTrue(self.check())

    def test_wrong_stage(self):
        self.data["stage"] = "captions"
        self.assertTrue(self.check())

    def test_ass_version_binding(self):
        self.check()
        ass = self.root / "captions.ass"
        ass.write_text("test", encoding="utf-8")
        self.assertTrue(validate_report(self.report, "rough-cut",
                                        {"source": self.source, "ass": ass}))

    def test_malformed_report(self):
        self.report.write_text("[]", encoding="utf-8")
        self.assertTrue(validate_report(self.report, "rough-cut", {"source": self.source}))

    def test_caption_entry_blocks_before_media_processing(self):
        self.data["checks"]["G5"]["status"] = "failed"
        self.check()
        output = self.root / "not-created"
        result = subprocess.run([
            sys.executable, str(Path(__file__).with_name("run_pipeline.py")),
            "captions", "--source", str(self.source), "--script", str(self.source),
            "--output-dir", str(output), "--font-name", "fixture",
            "--font-file", str(self.source), "--approval-report", str(self.report),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")
        self.assertFalse(output.exists())

    def test_preview_entry_blocks_without_caption_approval(self):
        self.check()
        output = self.root / "not-created.mp4"
        result = subprocess.run([
            sys.executable, str(Path(__file__).with_name("run_pipeline.py")),
            "preview", "--source", str(self.source), "--background", str(self.source),
            "--ass", str(self.source), "--font-file", str(self.source),
            "--output", str(output), "--mask-shape", "circle", "--subject-crop-y", "0",
            "--approval-report", str(self.report),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
