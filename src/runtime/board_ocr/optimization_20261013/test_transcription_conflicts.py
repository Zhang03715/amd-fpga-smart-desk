import unittest
from .transcription_conflicts import resolve


class ConflictTests(unittest.TestCase):
    def rows(self):
        return [dict(id=i,v4_text=text,v4_confidence=score,accepted=True,
                     points=[[10,10],[35,10],[35,180],[10,180]])
                for i,(text,score) in enumerate([('中国近现代史纲要',.985),
                    ('中国近现代史纲要',.958),('中国近现代史纲婴',.936)])]

    def test_two_distinct_strong_crops_can_reject_weaker_conflicting_title(self):
        rows=self.rows();result=resolve(rows,{0:'a',1:'b',2:'c'})
        self.assertEqual(result['rejected_ids'],[2]);self.assertFalse(rows[2]['accepted'])

    def test_duplicates_adjacent_books_and_high_confidence_conflicts_stay_unresolved(self):
        rows=self.rows();resolve(rows,{0:'a',1:'a',2:'c'})
        self.assertTrue(rows[2]['accepted'])
        rows=self.rows();rows[1]['points']=[[40,10],[65,10],[65,180],[40,180]]
        resolve(rows,{0:'a',1:'b',2:'c'});self.assertTrue(rows[2]['accepted'])
        rows=self.rows();rows[2]['v4_confidence']=.99
        resolve(rows,{0:'a',1:'b',2:'c'});self.assertTrue(rows[2]['accepted'])


if __name__=='__main__':unittest.main()
