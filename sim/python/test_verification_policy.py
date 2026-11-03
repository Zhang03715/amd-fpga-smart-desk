import unittest
from verification_policy import needs_review, decide


class VerificationTests(unittest.TestCase):
    def test_wrong_near_title_never_accepted(self):
        target='建筑业重点推广新技术应用手册'
        other='建筑业重点推广新技术应用平册'
        self.assertTrue(needs_review(target,other))
        self.assertFalse(decide(target,other,other,0.99)['accepted'])
        self.assertTrue(decide(target,other,target,0.95)['accepted'])

    def test_short_substring_and_low_confidence(self):
        self.assertFalse(needs_review('高等数学','西安交通大学高等数学教研室编'))
        self.assertFalse(decide('高等数学','高等数学','高等数学上册',0.99)['accepted'])
        self.assertFalse(decide('高等数学','高等数学','高等数学',0.89)['accepted'])

    def test_punctuation_only_and_empty(self):
        self.assertTrue(decide('工程数学—复变函数','工程数学复变函数','工程数学—复变函数',0.95)['accepted'])
        self.assertFalse(decide('','','',1)['accepted'])


if __name__ == '__main__':
    unittest.main()
