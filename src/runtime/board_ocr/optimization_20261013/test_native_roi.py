import unittest
from .native_roi import choose,overlap


class NativeReviewTests(unittest.TestCase):
    def test_confident_local_correction_and_conflict_are_audited(self):
        self.assertEqual(choose('大学物现学',.82,'大学物理学',.96),(True,False))
        self.assertEqual(choose('大学物现学',.92,'大学物理学',.97),(True,True))

    def test_short_fragment_and_low_confidence_cannot_replace(self):
        self.assertFalse(choose('大学物理学第四版',.82,'大学物理学',.99)[0])
        self.assertFalse(choose('大学物现学',.82,'大学物理学',.89)[0])
        self.assertFalse(choose('大学物理学',.98,'大学物现学',.96)[0])

    def test_neighbour_box_does_not_correspond(self):
        self.assertEqual(overlap([0,0,10,100],[20,0,30,100]),0)
