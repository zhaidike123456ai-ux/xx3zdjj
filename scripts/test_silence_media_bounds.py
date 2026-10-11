"""Silence/media timeline regressions; stdlib only and explicit UTF-8 fixtures."""
import json
from pathlib import Path
import tempfile
import unittest

from silence_review import (decoded_duration_diagnostic, parse_silence,
                            parse_silence_measurements)


class SilenceMediaBoundsTests(unittest.TestCase):
    def test_padded_pcm_tail_does_not_create_invalid_media_alert(self):
        log = 'silence_start: 23.613437\nsilence_end: 24.064 | silence_duration: 0.450563'
        rows = parse_silence(log, 24.05)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['start'], 23.613437)
        self.assertEqual(rows[0]['end'], 24.05)
        self.assertAlmostEqual(rows[0]['duration'], .436563)
        self.assertLessEqual(rows[0]['end'], 24.05)
        audit = parse_silence_measurements(log, 24.05)
        measured = audit['measurements'][0]
        self.assertEqual(measured['raw_end'], 24.064)
        self.assertEqual(measured['raw_reported_duration'], .450563)
        self.assertAlmostEqual(measured['end_adjustment_seconds'], -.014)
        self.assertAlmostEqual(measured['clipped_duration_seconds'], .014)
        self.assertFalse(audit['review_required'])

    def test_padding_only_silence_is_not_a_media_interval_but_audit_is_retained(self):
        log = 'silence_start: 24.055\nsilence_end: 24.064 | silence_duration: 0.009'
        self.assertEqual(parse_silence(log, 24.05), [])
        measured = parse_silence_measurements(log, 24.05)['measurements'][0]
        self.assertFalse(measured['retained'])
        self.assertEqual(measured['raw_start'], 24.055)
        self.assertEqual(measured['raw_end'], 24.064)
        self.assertEqual(measured['drop_reason'], 'empty_after_media_clamp')
        self.assertAlmostEqual(measured['clipped_duration_seconds'], .009)
        self.assertEqual(measured['duration'], 0)

    def test_real_interior_pause_and_unterminated_tail_remain(self):
        log = ('silence_start: 6.37\nsilence_end: 6.737 | silence_duration: 0.367\n'
               'silence_start: 23.613437')
        audit = parse_silence_measurements(log, 24.05)
        self.assertEqual([(row['start'],row['end']) for row in audit['intervals']],
                         [(6.37,6.737),(23.613437,24.05)])
        self.assertEqual(audit['measurements'][1]['end_source'], 'media_duration_fallback')
        self.assertIsNone(audit['measurements'][1]['raw_end'])
        self.assertEqual(audit['measurements'][1]['inferred_end'], 24.05)

    def test_negative_and_scientific_measurements_are_clamped(self):
        rows = parse_silence('silence_start: -1.25e-2\n'
                             'silence_end: +2.5E-1 | silence_duration: .2625', 1)
        self.assertEqual(rows, [{'start':0., 'end':.25, 'duration':.25}])

    def test_reversed_or_zero_measurements_do_not_create_intervals(self):
        audit = parse_silence_measurements('silence_start: 2\nsilence_end: 1\n'
                                           'silence_start: 3\nsilence_end: 3', 5)
        self.assertEqual(audit['intervals'], [])
        self.assertEqual([x['drop_reason'] for x in audit['measurements']],
                         ['reversed_measurement', 'zero_duration'])
        self.assertTrue(audit['review_required'])

    def test_unterminated_padding_only_start_does_not_invent_negative_duration(self):
        audit = parse_silence_measurements('silence_start: 24.055', 24.05)
        self.assertEqual(audit['intervals'], [])
        self.assertEqual(audit['measurements'][0]['duration'], 0)
        self.assertFalse(audit['review_required'])

    def test_missing_start_does_not_shift_next_interval(self):
        audit = parse_silence_measurements('silence_end: 1 | silence_duration: 1\n'
                                           'silence_start: 2\nsilence_end: 3 | silence_duration: 1', 5)
        self.assertEqual(audit['intervals'], [{'start':2.,'end':3.,'duration':1.}])
        self.assertEqual(audit['measurements'][0]['drop_reason'], 'missing_start')
        self.assertTrue(audit['review_required'])

    def test_successive_starts_are_not_falsely_paired(self):
        audit = parse_silence_measurements('silence_start: 1\nsilence_start: 2\n'
                                           'silence_end: 3 | silence_duration: 1', 5)
        self.assertEqual(audit['intervals'], [{'start':2.,'end':3.,'duration':1.}])
        self.assertEqual(audit['measurements'][0]['drop_reason'], 'missing_end_before_next_start')
        self.assertTrue(audit['review_required'])

    def test_nonfinite_or_malformed_time_is_audited_and_never_json_nan(self):
        for raw in ('nan', 'inf', '-Infinity', '1e999', 'not-a-time'):
            with self.subTest(raw=raw):
                audit = parse_silence_measurements(f'silence_start: {raw}\nsilence_end: 1', 5)
                self.assertEqual(audit['intervals'], [])
                self.assertEqual(audit['measurements'][0]['raw_start_text'], raw)
                self.assertTrue(audit['review_required'])
                json.dumps(audit, allow_nan=False)

    def test_invalid_reported_duration_keeps_valid_bounds_with_diagnostic(self):
        audit = parse_silence_measurements('silence_start: 1\nsilence_end: 2 | silence_duration: nan', 5)
        self.assertEqual(audit['intervals'], [{'start':1.,'end':2.,'duration':1.}])
        self.assertTrue(audit['review_required'])
        self.assertEqual(audit['diagnostics'][0]['code'], 'invalid_reported_silence_duration')

    def test_numeric_overflow_never_leaks_nonfinite_audit_values(self):
        audit = parse_silence_measurements('silence_start: -1e308\nsilence_end: 1e308', 5)
        self.assertEqual(audit['intervals'], [])
        self.assertTrue(audit['review_required'])
        self.assertEqual(audit['measurements'][0]['drop_reason'], 'nonfinite_measurement_span')
        json.dumps(audit, allow_nan=False)

    def test_inconsistent_reported_duration_is_not_used_as_media_duration(self):
        audit = parse_silence_measurements('silence_start: 1\nsilence_end: 2 | silence_duration: 7', 5)
        self.assertEqual(audit['intervals'][0]['duration'], 1.)
        self.assertEqual(audit['measurements'][0]['raw_reported_duration'], 7.)
        self.assertTrue(audit['review_required'])

    def test_invalid_media_duration_rejected(self):
        for duration in (-1, float('nan'), float('inf'), 'not-a-duration'):
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    parse_silence('', duration)

    def test_utf8_chinese_fixture_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'silence_fixture.txt'
            path.write_text('原片：我我发现\nsilence_start: 1\nsilence_end: 2', encoding='utf-8')
            audit = parse_silence_measurements(path.read_text(encoding='utf-8'), 5)
            output = Path(folder) / 'audit.json'
            output.write_text(json.dumps({'说明':'正常词与原始证据', **audit}, ensure_ascii=False,
                                         allow_nan=False), encoding='utf-8')
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))['说明'], '正常词与原始证据')
            self.assertEqual(audit['intervals'][0]['end'], 2)


class DecodedDurationDiagnosticTests(unittest.TestCase):
    def test_aac_14ms_padding_is_not_swallowed_speech(self):
        result = decoded_duration_diagnostic(24.05, 24.064)
        self.assertEqual(result['status'], 'within_tolerance')
        self.assertFalse(result['review_required'])
        self.assertAlmostEqual(result['difference_seconds'], .014)
        self.assertEqual(result['threshold_seconds'], .1)

    def test_large_difference_requires_technical_review_in_both_directions(self):
        for decoded in (23.5, 24.7):
            with self.subTest(decoded=decoded):
                result = decoded_duration_diagnostic(24.05, decoded)
                self.assertEqual(result['status'], 'review_required')
                self.assertTrue(result['review_required'])
                self.assertIn('not evidence of swallowed speech', result['reason'])

    def test_threshold_is_capped_and_explicit(self):
        self.assertEqual(decoded_duration_diagnostic(300,300)['threshold_seconds'], .3)
        result = decoded_duration_diagnostic(3600,3601)
        self.assertEqual(result['threshold_seconds'], .5)
        self.assertTrue(result['review_required'])

    def test_invalid_decoded_duration_or_policy_rejected(self):
        for invalid in (-1, float('nan'), float('inf')):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    decoded_duration_diagnostic(24.05, invalid)
        with self.assertRaises(ValueError):
            decoded_duration_diagnostic(1,1,maximum_threshold_seconds=.01)


if __name__ == '__main__':
    unittest.main()
