import unittest
from .rotated_review import restore_points,choose,needs_padding


class RotatedReviewTests(unittest.TestCase):
    def test_pruning_cannot_change_selection_for_any_padding_result(self):
        for primary in [('原始文字',.1),('原始文字',.899),('原始文字',.90),('原始文字',.99)]:
            for secondary in [('补检文字',.89),('补检文字',.90),('短',.99),('补检文字',.99)]:
                if needs_padding(primary,secondary):continue
                for padded in [('补检文字',1.),('不同文字',1.),('',0.)]:
                    self.assertEqual(choose(primary,secondary,padded)[0],primary)

    def test_inverse_rotation_preserves_original_roi_coordinates(self):
        self.assertEqual(restore_points([[10,20],[30,20],[30,40],[10,40]],100,50,200).tolist(),
                         [[120,239],[120,219],[140,219],[140,239]])

    def test_weak_primary_rescue_requires_two_matching_confident_reads(self):
        result,audit=choose(('太学物理实验',.84),('大学物理实验',.93),('大学物理实验',.92))
        self.assertEqual(result,('大学物理实验',.92));self.assertTrue(audit['selected'])
        for padded in (('大学物理实脸',.99),('大学物理实验',.89)):
            result,audit=choose(('太学物理实验',.84),('大学物理实验',.93),padded)
            self.assertEqual(result,('太学物理实验',.84));self.assertFalse(audit['selected'])

    def test_high_confidence_disagreement_is_audited_not_overwritten(self):
        result,audit=choose(('太学物理实验',.99),('大学物理实验',.95),('大学物理实验',.94))
        self.assertEqual(result,('太学物理实验',.99));self.assertTrue(audit['conflict'])
