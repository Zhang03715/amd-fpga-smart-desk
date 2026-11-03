import unittest
from .consensus import book_title_key,BookFrameConsensus
from .test_consensus import result,info


class EditionMatchingTests(unittest.TestCase):
    def test_only_explicit_edition_suffixes_are_ignored(self):
        for text in ('大学物理学（第四版）','大学物理学(第4版)','大学物理学 第四版',
                     '大学物理学（四版）','《大学物理学（2023年版）》',
                     '大学物理学（修订版）','大学物理学（第4版）（修订版）'):
            self.assertEqual(book_title_key(text),'大学物理学',text)
        for text in ('大学物理实验','大学物理学（上册）','中国（现代）史','第二版图书馆','第四版'):
            self.assertNotEqual(book_title_key(text),'大学物理学')
        self.assertEqual(book_title_key('大学物理学（上册）'),'大学物理学上册')
        self.assertEqual(book_title_key('第四版'),'第四版')

    def test_query_and_observation_both_ignore_edition(self):
        for query,text in [('大学物理学','大学物理学（第四版）'),
                           ('大学物理学（第三版）','大学物理学（第四版）'),
                           ('大学物理学（第四版）','大学物理学')]:
            c=BookFrameConsensus(query)
            self.assertIsNotNone(c.observe(result(text=text),info(1)))
        c=BookFrameConsensus('大学物理学')
        self.assertIsNone(c.observe(result(text='大学物理实验'),info(1)))

    def test_different_edition_reads_same_position_are_one_candidate(self):
        r=result(text='大学物理学（第四版）',confidence=.99)
        r['matches']+=result(text='大学物理学（第三版）')['matches']
        c=BookFrameConsensus('大学物理学');self.assertIsNotNone(c.observe(r,info(1)))
        self.assertEqual(c.info()['frames'][0]['matching_candidates'],1)
        self.assertEqual(c.info()['frames'][0]['matching_text_variants'],2)

    def test_two_physical_copies_remain_ambiguous(self):
        r=result(text='大学物理学（第四版）')
        r['matches']+=result(text='大学物理学（第三版）',box=(100,20,150,200))['matches']
        c=BookFrameConsensus('大学物理学');self.assertIsNone(c.observe(r,info(1)))
        self.assertEqual(c.info()['frames'][0]['matching_candidates'],2)

    def test_edition_does_not_bypass_confidence_and_model_conflict(self):
        c=BookFrameConsensus('大学物理学')
        self.assertIsNone(c.observe(result(text='大学物理学（第四版）',confidence=.89),info(1)))
        self.assertIsNone(c.observe(result(text='大学物理学（第四版）',conflict=True),info(2)))
        self.assertIsNotNone(c.observe(result(text='大学物理学（第二版）'),info(3)))


if __name__=='__main__':unittest.main()
