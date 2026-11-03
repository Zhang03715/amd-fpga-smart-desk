import unittest
from expanded_title_review import use_expanded_text

class ExpandedReviewTests(unittest.TestCase):
    def test_recovers_leading_character_but_rejects_substitution(self):
        self.assertTrue(use_expanded_text('工智能概论','人工智能概论',.99))
        self.assertFalse(use_expanded_text('应用平册','应用手册',.99))
        self.assertFalse(use_expanded_text('人工智能概论','人工智能概论（',.99))
        self.assertFalse(use_expanded_text('工智能概论','人工智能概论',.89))
        self.assertFalse(use_expanded_text('高等数学','高等数学上',.99,'高等数学'))
        self.assertTrue(use_expanded_text('工智能概论','人工智能概论',.99,'人工智能概论'))

if __name__=='__main__': unittest.main()
