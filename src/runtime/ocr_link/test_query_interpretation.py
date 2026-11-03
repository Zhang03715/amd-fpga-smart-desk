import unittest
from .consensus import repeated_prefix_query,BookFrameConsensus


class QueryTests(unittest.TestCase):
    def test_only_repeated_multicharacter_chinese_prefix_is_interpreted(self):
        self.assertEqual(repeated_prefix_query('大学大学物理学'),'大学物理学')
        self.assertEqual(repeated_prefix_query('马克马克思主义基本原理'),'马克思主义基本原理')
        for text in ('人人都爱物理学','大学物理学','C++程序设计','高等数学','大学大学'):
            self.assertIsNone(repeated_prefix_query(text))

    def test_alias_consensus_never_uses_single_high_confidence_frame(self):
        c=BookFrameConsensus('大学物理学',allow_fast_path=False)
        r=dict(matches=[dict(text='大学物理学',ocr_confidence=.99,book_box=[1,2,3,4])])
        self.assertIsNone(c.observe(r,dict(sequence=1,captured_monotonic=1.,device='test')))
        self.assertIsNotNone(c.observe(r,dict(sequence=2,captured_monotonic=2.,device='test')))
