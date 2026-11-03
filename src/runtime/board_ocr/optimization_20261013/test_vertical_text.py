import unittest
import numpy as np
from .vertical_text import reflow,select,select_strong,review


class VerticalTextTests(unittest.TestCase):
    def test_strong_review_corrects_uncertain_text_only_with_tight_agreement(self):
        correct=('大学生军事理论教程',.994)
        self.assertTrue(select_strong(('大学生军事理论教图',.948),correct,('大学生军事理论教程',.99),9))
        for old,other,count in [(('大学生军事理论教图',.96),correct,9),
                                 (('大学生军事理论教图',.948),('大学生军事理论教程',.94),9),
                                 (('大学生军事理论教图',.948),('大学生军事理论教图',.999),9),
                                 (('大学生军事理论教图',.948),correct,10)]:
            self.assertFalse(select_strong(old,correct,other,count))

    def test_strong_failure_keeps_legacy_low_confidence_recovery(self):
        line=np.full((48,7*48,3),200,np.uint8)
        strong=lambda images:([['积分变换与场论',.94],['积分变换与场论',.98]],.02)
        primary=lambda images:([['积分变换与场论',.924],['积分变换与场论',.921]],.03)
        result,audit=review(('银分变换与场论',.78),line,7,primary,strong)
        self.assertEqual(result,('积分变换与场论',.921));self.assertTrue(audit['selected'])
        self.assertEqual(audit['selected_model'],'primary_glyph')
        self.assertEqual(len(audit['attempts']),2)

    def test_synthetic_column_preserves_glyph_orientation_and_top_to_bottom_order(self):
        image=np.full((200,50,3),240,np.uint8)
        for i in range(5):
            y=12+i*30
            # Unequal stems make an accidental 90/180 degree rotation visible.
            image[y:y+4,13:31]=20
            image[y:y+20,13:17]=20
            image[y+16:y+20,17:25+i]=20
        prepared=reflow(image,[[5,0],[40,0],[40,180],[5,180]])
        self.assertIsNotNone(prepared)
        line,audit=prepared
        self.assertEqual(audit['character_cells'],5)
        self.assertEqual(line.shape,(48,240,3))
        for i in range(5):
            mask=line[:,48*i:48*(i+1),0]<100
            self.assertGreater(mask[:24].sum(),mask[24:].sum())

    def test_horizontal_or_single_glyph_cannot_be_reflowed(self):
        image=np.full((100,200,3),240,np.uint8)
        self.assertIsNone(reflow(image,[[0,0],[180,0],[180,30],[0,30]]))
        self.assertIsNone(reflow(image,[[0,0],[25,0],[25,80],[0,80]]))

    def test_selection_requires_full_cell_count_and_two_confident_matching_reads(self):
        good=('积分变换与场论',.93)
        self.assertTrue(select(('银分变换与场论',.78),good,('积分变换与场论',.92),7))
        for original,other,cells in [(('银分变换与场论',.95),good,7),
                                      (('银分变换与场论',.78),('积分变换与场化',.98),7),
                                      (('银分变换与场论',.78),('积分变换与场论',.89),7),
                                      (('银分变换与场论',.78),good,8)]:
            self.assertFalse(select(original,good,other,cells))
        self.assertFalse(select(('',.1),('C程序设计',.99),('C程序设计',.99),5))


if __name__=='__main__':unittest.main()
