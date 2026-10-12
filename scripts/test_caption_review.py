"""Standard-library synthetic regressions; no private speech/listening claims."""
import array
import copy
import hashlib
import json
import math
import tempfile
import unittest
import wave
from pathlib import Path

from caption_review import plan_caption_layout, review_caption_timing


SOURCE = hashlib.sha256(b'synthetic approved final media').hexdigest()


class CaptionTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def review(self, words, **kwargs):
        return review_caption_timing(words, duration=10, source_sha256=SOURCE, **kwargs)

    def evidence(self, words, report, *, index=0, measured=None, resolution='retain', flag_ids=None):
        word = words[index]
        record = {
            'kind': 'caption_local_machine_review', 'source_sha256': SOURCE,
            'word_index': index, 'original_word': copy.deepcopy(word),
            'window': {'start': 0, 'end': 10}, 'method': 'synthetic_local_machine_alignment',
            'reviewer': 'synthetic-test-agent', 'recorded_at': 'synthetic',
            'assessment': 'SYNTHETIC fixture measures this word; no listening claim.',
            'flag_ids': flag_ids or [x['id'] for x in report['flags'] if x['word_index'] == index],
            'resolution': resolution,
            'verification': 'confirmed',
            'measured_word': measured or {k: word[k] for k in ('word', 'start', 'end')},
        }
        target = self.root / f'review_{index}.json'
        target.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return {'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}

    def rewrite(self, reference, mutate):
        target = Path(reference['path'])
        record = json.loads(target.read_text(encoding='utf-8'))
        mutate(record)
        target.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return dict(reference, sha256=hashlib.sha256(target.read_bytes()).hexdigest())

    def test_long_legal_words_crossing_silence_stay_unresolved_without_shrinking(self):
        words = [{'word': '孩', 'start': 1, 'end': 2.86}, {'word': '就', 'start': 3, 'end': 4.36}]
        result = self.review(words, silences=[{'start': 1.4, 'end': 2.7}, {'start': 3.4, 'end': 4.1}])
        self.assertEqual(result['words'], words)
        self.assertEqual(result['quality_status'], 'review_required')
        self.assertEqual(len(result['flags']), 4)
        self.assertEqual({f['code'] for f in result['flags']}, {'unusually_long_word', 'word_silence_conflict'})
        self.assertTrue(all(not f['automatic_correction'] for f in result['flags']))

    def test_retaining_inconclusive_timing_is_not_clearance(self):
        words=[{'word':'孩','start':1.,'end':2.86}]
        report=self.review(words)
        reference=self.evidence(words,report)
        reference=self.rewrite(reference,lambda d:d.update(verification='inconclusive',assessment='Cannot determine timing; preserve original.'))
        result=self.review(words,local_reviews=[reference],base_dir=self.root)
        self.assertEqual(result['quality_status'],'review_required')
        self.assertTrue(result['unresolved_flags'])
        self.assertFalse(result['accepted_reviews'])

    def test_known_pcm_onset_finds_two_tenths_early_and_evidence_fixes_only_that_word(self):
        # The PCM signal itself starts at exactly 1.0 s; this is neither speech
        # recognition nor a claimed real-person phonetic acceptance test.
        samples = array.array('h', [0] * 16000 + [6000] * 8000)
        wav = self.root / 'known_onset.wav'
        with wave.open(str(wav), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
            stream.writeframes(samples.tobytes())
        with wave.open(str(wav), 'rb') as stream:
            decoded = array.array('h'); decoded.frombytes(stream.readframes(stream.getnframes()))
            onset = next(i for i, value in enumerate(decoded) if abs(value) >= 1000) / stream.getframerate()
        words = [{'word': '第三个', 'start': .8, 'end': 1.5}, {'word': '问题', 'start': 2, 'end': 2.4}]
        onsets = [{'source_sha256': SOURCE, 'word_index': 0, 'onset': onset, 'method': 'known_pcm_threshold_onset'}]
        report = self.review(words, onset_evidence=onsets)
        flag = report['flags'][0]
        self.assertEqual(flag['code'], 'onset_disagreement')
        self.assertAlmostEqual(flag['detail']['asr_minus_measured_seconds'], -.2)
        reference = self.evidence(words, report, measured={'word': '第三个', 'start': onset, 'end': 1.5}, resolution='replace_timing')
        result = self.review(words, onset_evidence=onsets, local_reviews=[reference])
        self.assertEqual(result['quality_status'], 'machine_checked')
        self.assertEqual(result['words'][0]['start'], 1)
        self.assertEqual(result['words'][1], words[1])
        self.assertEqual(words[0]['start'], .8)
        self.assertFalse(result['scope']['phonetic_accuracy_certified'])
        self.assertFalse(result['scope']['listening_required'])

    def test_normal_measured_prolongation_can_be_retained_without_listening(self):
        words = [{'word': '好', 'start': 1, 'end': 2.2, 'probability': .92}]
        report = self.review(words)
        self.assertEqual(report['quality_status'], 'review_required')
        reference = self.evidence(words, report)
        result = self.review(words, local_reviews=[reference])
        self.assertEqual(result['quality_status'], 'machine_checked')
        self.assertEqual(result['words'], words)
        self.assertEqual(result['flags'][0]['status'], 'resolved_by_local_machine_review')

    def test_partial_resolution_cannot_hide_silence_conflict(self):
        words = [{'word': '就', 'start': 1, 'end': 2.36}]
        silences = [{'start': 1.2, 'end': 2}]
        report = self.review(words, silences=silences)
        reference = self.evidence(words, report, flag_ids=[report['flags'][0]['id']])
        result = self.review(words, silences=silences, local_reviews=[reference])
        self.assertEqual(result['quality_status'], 'review_required')
        self.assertEqual([x['code'] for x in result['unresolved_flags']], ['word_silence_conflict'])

    def test_wrong_source_stale_full_record_hash_and_flag_do_not_resolve(self):
        words = [{'word': '孩', 'start': 1, 'end': 2.86, 'probability': .91}]
        report = self.review(words)
        for name, mutate in [
            ('source', lambda d: d.update(source_sha256='0' * 64)),
            ('word', lambda d: d['original_word'].pop('probability')),
            ('flag', lambda d: d.update(flag_ids=['caption-other'])),
            ('measurement', lambda d: d['measured_word'].update(word='孩子')),
            ('window', lambda d: d['window'].update(start=2)),
            ('listening', lambda d: d.update(method='human_listening')),
            ('interpolation', lambda d: d.update(method='character_interpolation')),
            ('nonfinite', lambda d: d['measured_word'].update(end=float('nan'))),
        ]:
            with self.subTest(name=name):
                ref = self.rewrite(self.evidence(words, report), mutate)
                result = self.review(words, local_reviews=[ref])
                self.assertEqual(result['quality_status'], 'review_required')
                self.assertTrue(result['rejected_reviews'])
                self.assertEqual(result['words'], words)
        ref = self.evidence(words, report)
        Path(ref['path']).write_text('{}', encoding='utf-8')
        self.assertTrue(self.review(words, local_reviews=[ref])['rejected_reviews'])

    def test_new_conflict_after_correction_still_blocks(self):
        words = [{'word': '孩', 'start': 1, 'end': 2.86}, {'word': '跑', 'start': 3, 'end': 3.4}]
        report = self.review(words)
        reference = self.evidence(words, report, measured={'word': '孩', 'start': 2.7, 'end': 3.2}, resolution='replace_timing')
        result = self.review(words, local_reviews=[reference])
        self.assertEqual(result['quality_status'], 'review_required')
        self.assertIn('word_overlap', [x['code'] for x in result['unresolved_flags']])

    def test_duplicate_silences_do_not_inflate_overlap(self):
        words = [{'word': '这个', 'start': 1, 'end': 1.8}]
        interval = {'start': 1, 'end': 1.12}
        result = self.review(words, silences=[interval, interval])
        self.assertFalse(result['flags'])

    def test_no_measurements_never_claims_phonetic_validation(self):
        result = self.review([{'word': '测试', 'start': 1, 'end': 1.5}])
        self.assertEqual(result['quality_status'], 'machine_checked')
        self.assertEqual(result['scope']['onset_measurements_supplied'], 0)
        self.assertFalse(result['scope']['phonetic_accuracy_certified'])

    def test_invalid_ranges_or_unavailable_evidence_cannot_look_clean(self):
        for start, end in [(1, 1), (-.1, .2), (1, float('inf')), (9, 11)]:
            result = self.review([{'word': '上', 'start': start, 'end': end}])
            self.assertEqual(result['quality_status'], 'review_required')
            self.assertEqual(result['flags'][0]['code'], 'invalid_word_timing')
        self.assertEqual(self.review([])['quality_status'], 'review_required')
        with self.assertRaises(ValueError):
            self.review([{'word': '上', 'start': 1, 'end': 1.2}], silences=[{'start': 9, 'end': 11}])
        with self.assertRaises(ValueError):
            self.review([{'word': '上', 'start': 1, 'end': 1.2}], onset_evidence=[
                {'word_index': 0, 'source_sha256': '0'*64, 'onset': 1, 'method': 'pcm'}])


class CaptionLayoutTests(unittest.TestCase):
    @staticmethod
    def words(*tokens):
        return [{'word': token, 'start': i, 'end': i+.5} for i, token in enumerate(tokens)]

    def test_known_weak_breaks_merge_without_losing_text(self):
        for chunks in [['不是先堆', '一大串复杂词'], ['再替换成', '自己的画面主题']]:
            result = plan_caption_layout(chunks, words=self.words(*chunks))
            self.assertEqual(result['chunks'], [''.join(chunks)])
            self.assertEqual(result['status'], 'ready')
            self.assertTrue(result['text_preserved'])
            self.assertFalse(result['timing_changed'])

    def test_known_predicate_reflows_only_at_complete_measured_words(self):
        chunks = ['真正要先想明白', '的是四件事']
        result = plan_caption_layout(chunks, words=self.words('真正', '要先', '想明白的', '是', '四件事'))
        self.assertEqual(result['chunks'], ['真正要先想明白的是\n四件事'])
        self.assertFalse(result['timing_changed'])
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(result['text_preserved'])

    def test_predicate_keeps_overlong_line_when_asr_token_cannot_be_split(self):
        chunks = ['真正要先想明白', '的是四件事']
        result = plan_caption_layout(chunks, words=self.words('真正要先想明白', '的是四件事'))
        self.assertEqual(result['chunks'], [''.join(chunks)])
        self.assertEqual(result['status'], 'review_required')
        self.assertTrue(any(x['code'] == 'line_too_long' for x in result['issues']))
        self.assertFalse(result['timing_changed'])

    def test_long_unknown_sentence_is_not_split_by_character_count(self):
        text = '只要在图片上画出一条你想要的运动路线'
        result = plan_caption_layout([text], words=self.words(text), max_chars=5)
        self.assertEqual(result['chunks'], [text])
        self.assertEqual(result['status'], 'review_required')
        self.assertTrue(result['text_preserved'])

    def test_explicit_layout_retains_content_and_complete_word_timing(self):
        chunks = ['想把空间关系交代清楚']
        words = self.words('想把', '空间关系', '交代清楚')
        result = plan_caption_layout(chunks, words=words, trusted_layout=['想把空间关系', '交代清楚'])
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(result['explicit_layout_used'])
        self.assertTrue(result['text_preserved'])
        self.assertEqual(words, self.words('想把', '空间关系', '交代清楚'))

    def test_explicit_layout_rejects_loss_weak_break_and_intra_token_boundary(self):
        chunks = ['不是先堆一大串复杂词']
        words = self.words('不是', '先堆', '一大串', '复杂词')
        bad_layouts = [(['是先堆一大串复杂词'], 'layout_text_changed'),
                       (['不是先堆', '一大串复杂词'], 'weak_semantic_boundary'),
                       (['不是先堆一', '大串复杂词'], 'boundary_inside_asr_word')]
        for layout, code in bad_layouts:
            with self.subTest(layout=layout):
                result = plan_caption_layout(chunks, words=words, trusted_layout=layout)
                self.assertEqual(result['status'], 'review_required')
                self.assertIn(code, [row['code'] for row in result['issues']])

    def test_existing_good_layout_and_punctuation_stay_unchanged(self):
        chunks = ['不是工具，', '而是判断。']
        result = plan_caption_layout(chunks, words=self.words('不是', '工具', '而是', '判断'))
        self.assertEqual(result['chunks'], chunks)
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(result['text_preserved'])


if __name__ == '__main__':
    unittest.main()
