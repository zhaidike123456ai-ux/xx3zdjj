import unittest
from pause_policy import plan_pauses, quantize_deletions


class PausePolicyTests(unittest.TestCase):
    def test_each_leading_island_is_accounted_for(self):
        rows=plan_pauses([dict(start=0,end=.5),dict(start=1.5,end=2.7)],
                         [dict(word='我',start=3,end=3.2)],4)
        self.assertEqual(len(rows),2)
        self.assertTrue(all(x['proposed_delete_start'] != '' for x in rows))
        self.assertGreaterEqual(float(rows[1]['proposed_delete_start']),1.5)

    def test_quiet_word_conflict_is_not_an_executable_proposal(self):
        row=plan_pauses([dict(start=1,end=2.5)],[dict(word='不',start=1.2,end=1.5)],4)[0]
        self.assertEqual(row['decision'],'review_word_silence_conflict')
        self.assertEqual(row['proposed_delete_start'],'')
        self.assertEqual(row['word_conflicts'],[0])

    def test_total_gap_target_depends_on_phrase_boundary(self):
        silence=[dict(start=1,end=1.6)]
        within=plan_pauses(silence,[dict(word='因为',start=.5,end=.9)],3)[0]
        sentence=plan_pauses(silence,[dict(word='结束。',start=.5,end=.9)],3)[0]
        self.assertAlmostEqual(.6-(float(within['proposed_delete_end'])-float(within['proposed_delete_start'])),.14)
        self.assertEqual(sentence['target_pause_seconds'],.24)

    def test_short_gap_retained_without_expansion(self):
        row=plan_pauses([dict(start=1,end=1.08)],[],3)[0]
        self.assertFalse(row['review_required'])
        self.assertAlmostEqual(row['retained_seconds'],.08)

    def test_quantization_cannot_remove_next_onset(self):
        actual,audit=quantize_deletions([(.5,1.019,'test')],'30',2)
        self.assertEqual(actual,[(.5,1.,'test')])
        self.assertLessEqual(actual[0][1],1.019)
        self.assertLess(actual[0][1],1.020)
        self.assertEqual(audit[0]['requested_end'],1.019)

    def test_ntsc_and_start_never_expand_authorized_removal(self):
        actual,_=quantize_deletions([(.501,1.019,'test')],'30000/1001',2)
        self.assertGreaterEqual(actual[0][0],.501)
        self.assertLessEqual(actual[0][1],1.019)


if __name__=='__main__':unittest.main()
