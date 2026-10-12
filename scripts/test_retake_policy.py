"""Deterministic ASR-text fixtures; do not certify actual speech or authorize cuts."""
import math
import unittest
from retake_policy import detect_retake_groups

A = '教程很简单第一步先准备一张图片'
B = '然后画出想要的飞行轨迹再输入提示词'


def attempts(texts=(A,B), offsets=(0,6)):
    return [dict(start=offset+2*i,end=offset+2*i+2,text=text)
            for offset in offsets for i,text in enumerate(texts)]


def chosen(row):
    return next(x for x in row['attempts'] if x['id']==row['selection']['attempt_id'])


class RetakePolicyTests(unittest.TestCase):
    def test_two_takes_legacy_keys_and_own_range(self):
        rows=detect_retake_groups(attempts(),'last_complete')
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(len(row['attempts']),2)
        self.assertEqual(chosen(row)['start'],6)
        self.assertEqual([(x['start'],x['end']) for x in row['proposed_delete_ranges']],[(0,4)])
        self.assertEqual(row['proposed_delete_end'],'4.000')
        for key in ('id','first_attempt_start','first_attempt_end','first_attempt_text','last_attempt_start',
                    'last_attempt_end','last_attempt_text','similarity','gap_seconds','policy','decision',
                    'proposed_delete_start','proposed_delete_end','kept_range','status'):
            self.assertIn(key,row)
        self.assertTrue(row['needs_semantic_review'])
        self.assertFalse(row['selection']['semantic_verified'])
        self.assertFalse(row['deletion_authorized'])

    def test_three_takes_choose_actual_last_and_propose_both_old_ranges(self):
        row=detect_retake_groups(attempts(offsets=(0,6,12)),'last_complete')[0]
        self.assertEqual(len(row['attempts']),3)
        self.assertEqual(chosen(row)['start'],12)
        self.assertEqual(row['last_attempt_start'],'12.000')
        self.assertEqual([(x['start'],x['end']) for x in row['proposed_delete_ranges']],[(0,4),(6,10)])
        self.assertEqual(row['proposed_delete_end'],'4.000')  # Never legacy 0->11.88 bridge.

    def test_rapid_three_and_four_takes_do_not_become_aba_rolling_windows(self):
        for offsets in ((0,4.4,8.8),(0,4.4,8.8,13.2)):
            with self.subTest(offsets=offsets):
                row=detect_retake_groups(attempts(offsets=offsets),'last_complete')[0]
                self.assertEqual(len(row['attempts']),len(offsets))
                self.assertEqual(chosen(row)['start'],offsets[-1])
                self.assertEqual(len(row['proposed_delete_ranges']),len(offsets)-1)
                self.assertTrue(all(len(a['segment_indices'])==2 for a in row['attempts']))

    def test_same_text_with_different_asr_segmentation_forms_one_group(self):
        data=[dict(start=0,end=4,text=A+B),dict(start=6,end=8,text=A),
              dict(start=8,end=10,text=B),dict(start=12,end=16,text=A+B)]
        row=detect_retake_groups(data,'last_complete')[0]
        self.assertEqual(len(row['attempts']),3)
        self.assertEqual(chosen(row)['start'],12)
        self.assertEqual([(x['start'],x['end']) for x in row['proposed_delete_ranges']],[(0,4),(6,10)])

    def test_four_restarts_can_chain_beyond_first_pair_twenty_seconds(self):
        row=detect_retake_groups(attempts(offsets=(0,10,20,30)),'last_complete')[0]
        self.assertEqual(len(row['attempts']),4)
        self.assertEqual(chosen(row)['start'],30)
        self.assertEqual(len(row['proposed_delete_ranges']),3)

    def test_none_detects_same_group_without_proposed_deletions(self):
        rows=detect_retake_groups(attempts(offsets=(0,6,12)),'none')
        self.assertEqual(len(rows[0]['attempts']),3)
        self.assertEqual(rows[0]['proposed_delete_ranges'],[])
        self.assertEqual(rows[0]['proposed_delete_start'],'')
        self.assertEqual(rows[0]['proposed_delete_end'],'')

    def test_missing_negation_is_not_last_correct_or_high_confidence_delete(self):
        first='差距不一定在工具而是你的提示词里少了判断'
        later=first.replace('不一定','一定')
        segments=[dict(start=0,end=2,text=first),dict(start=2,end=4,text=B),
                  dict(start=6,end=8,text=later),dict(start=8,end=10,text=B)]
        row=detect_retake_groups(segments,'last_complete',first+B)[0]
        self.assertIn('negation_or_condition_changed',row['semantic_warnings'])
        self.assertEqual(row['proposed_delete_ranges'],[])
        self.assertEqual(chosen(row)['start'],0)
        self.assertEqual(row['last_attempt_start'],'6.000')  # Still covers chronologically last wrong take.
        self.assertFalse(row['selection']['semantic_verified'])

    def test_missing_tail_prefers_more_text_not_false_complete_claim(self):
        full=B+'基本就能生成'
        partial=full[:-2]
        segments=[dict(start=0,end=2,text=A),dict(start=2,end=4,text=full),
                  dict(start=6,end=8,text=A),dict(start=8,end=10,text=partial)]
        row=detect_retake_groups(segments,'last_complete')[0]
        self.assertIn('later_attempt_missing_textual_tail',row['semantic_warnings'])
        self.assertEqual(chosen(row)['start'],0)
        self.assertFalse(row['selection']['semantic_verified'])
        self.assertEqual(row['proposed_delete_ranges'],[])

    def test_two_identical_dangling_attempts_do_not_become_complete(self):
        row=detect_retake_groups(attempts(texts=(A,B+'基本就能')),'last_complete')[0]
        self.assertIn('possible_incomplete_textual_ending',row['semantic_warnings'])
        self.assertEqual(row['proposed_delete_ranges'],[])

    def test_number_and_condition_changes_need_review(self):
        for first,later in [('只要输入提示词基本就可以生成视频','输入提示词基本就可以生成视频'),
                            ('这条视频生成需要十五秒也就是15秒','这条视频生成需要十五秒也就是50秒')]:
            with self.subTest(first=first):
                segments=[dict(start=0,end=2,text=first),dict(start=4,end=6,text=later)]
                row=detect_retake_groups(segments,'last_complete')[0]
                self.assertTrue(row['semantic_warnings'])
                self.assertEqual(row['proposed_delete_ranges'],[])

    def test_intervening_unique_sentence_survives_candidate_ranges(self):
        segments=attempts(offsets=(0,9))
        segments.insert(2,dict(start=5,end=7,text='这里先提醒大家图片不要包含文字'))
        row=detect_retake_groups(segments,'last_complete')[0]
        self.assertEqual([(x['start'],x['end']) for x in row['proposed_delete_ranges']],[(0,4)])
        self.assertEqual(row['intervening_segments'][0]['text'],'这里先提醒大家图片不要包含文字')
        self.assertIn('intervening_speech_must_be_preserved',row['semantic_warnings'])
        self.assertTrue(all(x['end']<=5 or x['start']>=7 for x in row['proposed_delete_ranges']))

    def test_contiguous_intervening_speech_not_sucked_into_wider_view(self):
        segments=attempts(offsets=(0,9))
        segments.insert(2,dict(start=4.1,end=5.6,text='另外千万不要使用带版权文字的图片'))
        row=detect_retake_groups(segments,'last_complete')[0]
        self.assertEqual([(x['start'],x['end']) for x in row['proposed_delete_ranges']],[(0,4)])
        self.assertEqual(row['intervening_segments'][0]['start'],4.1)

    def test_short_whole_sentence_one_second_gap_is_reviewed(self):
        rows=detect_retake_groups([dict(start=10,end=10.58,text='很简单'),
                                 dict(start=11.6,end=12.18,text='很简单')],'last_complete')
        self.assertTrue(rows)
        self.assertEqual(len(rows[0]['attempts']),2)
        self.assertEqual(chosen(rows[0])['start'],11.6)
        self.assertEqual(rows[0]['proposed_delete_ranges'],[])
        self.assertIn('lexical_or_emphasis_repetition_possible',rows[0]['semantic_warnings'])

    def test_short_restart_prefix_is_candidate_only(self):
        rows=detect_retake_groups([dict(start=10,end=10.6,text='而是你的提'),
                                 dict(start=11.6,end=13.5,text='而是你的提示词里少了判断')],'last_complete')
        self.assertTrue(rows)
        self.assertIn('earlier_attempt_is_textual_prefix_restart',rows[0]['semantic_warnings'])
        self.assertEqual(chosen(rows[0])['start'],11.6)
        self.assertEqual(rows[0]['proposed_delete_ranges'],[])

    def test_one_syllable_prefix_retry_never_infers_a_phoneme_cut(self):
        row=detect_retake_groups([dict(start=0,end=.2,text='我'),
                                dict(start=.4,end=2,text='我发现很多人还不知道这个玩法')],'last_complete')[0]
        self.assertEqual(row['proposed_delete_ranges'],[])
        self.assertFalse(row['deletion_authorized'])

    def test_lexical_reduplication_normal_emphasis_is_only_an_issue(self):
        for text in ('看看','慢慢','斜斜'):
            with self.subTest(text=text):
                row=detect_retake_groups([dict(start=0,end=.4,text=text)],'last_complete')[0]
                self.assertEqual(len(row['attempts']),1)
                self.assertEqual(row['proposed_delete_ranges'],[])
                self.assertTrue(row['needs_semantic_review'])
        row=detect_retake_groups([dict(start=0,end=.5,text='很重要'),
                                dict(start=1.5,end=2,text='很重要')],'last_complete')[0]
        self.assertEqual(row['proposed_delete_ranges'],[])

    def test_normal_distinct_list_not_retake(self):
        segments=[dict(start=i,end=i+.5,text=t) for i,t in enumerate(('远景','中景','特写'))]
        self.assertEqual(detect_retake_groups(segments,'last_complete'),[])

    def test_single_normal_sentence_with_reduplication_not_grouped(self):
        self.assertEqual(detect_retake_groups([dict(start=0,end=3,text='想把空间关系交代清楚就让镜头慢慢往后拉')],'last_complete'),[])

    def test_supplied_script_disagreement_not_ground_truth_or_proposal(self):
        row=detect_retake_groups(attempts(),'last_complete','这是另外一份不一致的稿件')[0]
        self.assertEqual(row['proposed_delete_ranges'],[])
        self.assertIn('no_attempt_exactly_supported_by_reference_substring',row['semantic_warnings'])
        self.assertFalse(row['selection']['semantic_verified'])

    def test_exact_reference_still_requires_semantic_and_acoustic_review(self):
        row=detect_retake_groups(attempts(),'last_complete',A+'。\n'+B)[0]
        self.assertTrue(row['proposed_delete_ranges'])
        self.assertFalse(row['selection']['semantic_verified'])
        self.assertTrue(row['needs_semantic_review'])
        self.assertTrue(all(x['requires_acoustic_evidence'] for x in row['proposed_delete_ranges']))

    def test_invalid_ranges_and_policy_fail_instead_of_fabricating_candidates(self):
        for start,end in ((0,0),(1,0),(-1,1),(0,float('nan')),(0,float('inf'))):
            with self.assertRaises(ValueError):
                detect_retake_groups([dict(start=start,end=end,text=A)],'last_complete')
        with self.assertRaises(ValueError):detect_retake_groups([], 'auto_delete')
        with self.assertRaises(ValueError):detect_retake_groups([], 'none', {})

    def test_empty_input_is_empty(self):
        self.assertEqual(detect_retake_groups([],'none'),[])

    def test_same_sentence_too_far_apart_not_a_local_restart(self):
        self.assertEqual(detect_retake_groups(attempts(texts=(A,),offsets=(0,50)),'last_complete'),[])

    def test_changed_source_order_keeps_original_indices_and_actual_chronology(self):
        data=attempts(offsets=(0,6,12))
        rows=detect_retake_groups(list(reversed(data)),'last_complete')
        self.assertEqual(chosen(rows[0])['start'],12)
        self.assertEqual(len(rows[0]['attempts']),3)


if __name__=='__main__':
    unittest.main()
