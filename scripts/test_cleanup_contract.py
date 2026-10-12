"""Independent cleanup contract regressions using temporary synthetic fixtures.

External FFmpeg/recognition are mocked where stated; pause, repeat, decision
export, acoustic-bound validation and frame quantization remain real code.
These tests never certify natural speech or manufacture real user approval.
"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import run_pipeline as pipeline
import test_retake_pipeline as fixtures


class CleanupDecisionContractTests(unittest.TestCase):
    def analysis_fixture(self):
        fixture = fixtures.AnalysisIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_every_pause_and_independent_opening_alert_reaches_decision_table(self):
        fixture = self.analysis_fixture()
        pauses = [{'start': 0, 'end': .8, 'duration': .8},
                  {'start': 1.1, 'end': 1.3, 'duration': .2},
                  {'start': 2, 'end': 2.08, 'duration': .08},
                  {'start': 3, 'end': 4.4, 'duration': 1.4}]
        opening = {'status': 'executed', 'reason': 'SYNTHETIC local decoder output',
                   'coverage': {'scope': 'opening_windows', 'start': 0, 'end': 2},
                   'alerts': [{'check_id': 'repeated_speech', 'start': .1, 'end': .6,
                               'text': '我 我发现', 'kind': 'opening_overlap_fixture',
                               'review_required': True}],
                   'windows': [], 'plan': {}}
        fixture.analyze([fixtures.word('我', 1, 1.25), fixtures.word('发现', 1.25, 1.6)],
                        silences=pauses, opening=opening)
        ledger = fixtures.read_csv(fixture.out / 'silence-candidates.csv')
        decisions = fixtures.read_csv(fixture.out / 'deletion-decisions.csv')
        self.assertEqual(len(ledger), 4)
        identifiers = {row['candidate_id'] for row in decisions}
        self.assertTrue({row['id'] for row in ledger} <= identifiers,
                        'retained, conflicting and proposed pauses all need a traceable decision row')
        for candidate in ledger:
            decision = next(row for row in decisions if row['candidate_id'] == candidate['id'])
            self.assertEqual(decision['delete_start'], candidate['proposed_delete_start'])
            self.assertEqual(decision['delete_end'], candidate['proposed_delete_end'])
        self.assertTrue(any('我 我发现' in (row.get('content', '') + row.get('evidence', ''))
                            for row in decisions), 'independent opening evidence must survive into the decision table')
        self.assertTrue(all(row['actual_execution'] == 'not_executed_in_analysis' for row in decisions))
        report = json.loads((fixture.out / 'review-report.json').read_text(encoding='utf-8'))
        self.assertTrue(any(row['kind'] == 'opening_overlap_fixture' for row in report['alerts']))
        self.assertTrue(any(row['kind'] == 'word_silence_conflict' for row in report['alerts']))
        self.assertEqual(report['quality_status'], 'review_required')

    def test_one_asr_segment_with_one_second_short_repeat_reaches_decision_and_alert(self):
        fixture = self.analysis_fixture()
        words = [fixtures.word('很简单', 1, 1.58), fixtures.word('很简单', 2.6, 3.18)]
        # fixtures.transcript intentionally puts both words in ONE segment.
        fixture.analyze(words, opening={'status': 'executed', 'reason': 'SYNTHETIC independent opening',
            'coverage': {'scope': 'opening_windows', 'start': 0, 'end': 1},
            'alerts': [], 'windows': [], 'plan': {}})
        decisions = fixtures.read_csv(fixture.out / 'deletion-decisions.csv')
        repeats = [row for row in decisions if row.get('content') == '很简单']
        self.assertTrue(repeats, 'same-segment short repeats must not depend on segment-level matching')
        self.assertTrue(all(not row['delete_start'] and not row['delete_end'] for row in repeats),
                        'a repeat candidate is not a safe phoneme cut or semantic acceptance')
        report = json.loads((fixture.out / 'review-report.json').read_text(encoding='utf-8'))
        self.assertTrue(any(row.get('text') == '很简单' and row['review_required'] for row in report['alerts']))
        self.assertEqual(report['quality_status'], 'review_required')

    def test_three_short_repeats_do_not_drop_the_second_restart(self):
        words = [fixtures.word('很简单', .1, .5), fixtures.word('很简单', 1.5, 1.9),
                 fixtures.word('很简单', 2.9, 3.3)]
        rows = pipeline.fragment_restart_candidates(words)
        self.assertEqual({row['start'] for row in rows if row.get('content') == '很简单'}, {.1, 1.5})
        self.assertTrue(all('delete_start' not in row and 'proposed_delete_start' not in row for row in rows))


class CleanupCutContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RoughCutBoundaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    @staticmethod
    def fake_render(command, **kwargs):
        target = Path(command[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'SYNTHETIC renderer output; not actual media acceptance')

    def render(self, request):
        with patch.object(pipeline, 'probe', return_value=self.fixture.meta), \
             patch.object(pipeline, 'run', side_effect=self.fake_render), \
             patch.object(pipeline, 'media_validation', return_value={'spec_status': 'passed'}), \
             redirect_stdout(io.StringIO()):
            return pipeline.rough_cut(request)

    def test_acoustic_start_cannot_expand_an_already_approved_delete_range(self):
        fixture = self.fixture
        fixture.row.update(delete_start='1.0', delete_end='1.5')
        fixture.write_decision()
        evidence = json.loads(fixture.evidence.read_text(encoding='utf-8'))
        evidence['last_complete_audio_onset'] = 2
        fixture.evidence.write_text(json.dumps(evidence), encoding='utf-8')
        # Measured failed onset .55 would yield .533333. That is outside the
        # approved [1,1.5] interval: request a revised decision, not a wider cut.
        with patch.object(pipeline, 'probe', return_value=fixture.meta), \
             patch.object(pipeline, 'run') as renderer:
            with self.assertRaisesRegex(SystemExit, 'approved|earlier|outside|expand|decision'):
                pipeline.rough_cut(fixture.args())
        renderer.assert_not_called()
        self.assertFalse(fixture.out.exists())

    def test_inward_quantized_end_uses_actual_boundary_and_keeps_onset(self):
        fixture = self.fixture
        # Approved end 1.019 precedes onset 1.020. At 30 fps actual removal ends
        # at 1.0, so the old ceil(1.019*30)=1.033 guard must not block this job.
        self.assertEqual(self.render(fixture.args()), 0)
        deleted = fixtures.read_csv(fixture.out / 'deleted-ranges.csv')
        self.assertEqual(len(deleted), 1)
        self.assertGreaterEqual(float(deleted[0]['source_start']), .5)
        self.assertEqual(float(deleted[0]['source_end']), 1.0)
        quantization = json.loads((fixture.out / 'cut-quantization.json').read_text(encoding='utf-8'))
        self.assertEqual(quantization[0]['requested_end'], 1.019)
        self.assertEqual(quantization[0]['actual_end'], 1.0)
        edit = json.loads((fixture.out / 'edit-map.json').read_text(encoding='utf-8'))
        self.assertEqual(edit['kept_segments'][1]['source_start'], 1.0)
        self.assertLess(edit['kept_segments'][1]['source_start'], 1.020)
        validation = json.loads((fixture.out / 'validation.json').read_text(encoding='utf-8'))
        self.assertEqual(validation['quality_status'], 'unverified')

    def test_actual_deletion_reaching_the_next_onset_is_still_blocked(self):
        fixture = self.fixture
        fixture.row['delete_end'] = '1.051'
        fixture.write_decision()
        with patch.object(pipeline, 'probe', return_value=fixture.meta), \
             patch.object(pipeline, 'run') as renderer:
            with self.assertRaisesRegex(SystemExit, 'onset|overlap'):
                pipeline.rough_cut(fixture.args())
        renderer.assert_not_called()

    def test_no_deletions_preserves_a_complete_subquarter_second_source(self):
        fixture = self.fixture
        fixture.meta['format']['duration'] = '0.12'
        request = fixture.args()
        request.approve_candidate = []
        request.decision_file = None
        self.assertEqual(self.render(request), 0)
        edit = json.loads((fixture.out / 'edit-map.json').read_text(encoding='utf-8'))
        self.assertEqual(edit['kept_segments'], [{'source_start': 0.0, 'source_end': .12,
                                                'output_start': 0.0, 'output_end': .12}])
        self.assertEqual(edit['deleted_source_ranges'], [])
        self.assertEqual(edit['planned_output_duration'], .12)


if __name__ == '__main__':
    unittest.main()
