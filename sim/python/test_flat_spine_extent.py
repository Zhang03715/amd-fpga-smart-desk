import unittest
import numpy as np
from flat_spine_extent import restore_flat_extent,_band_extent,_refine_truncated_seam


class FlatExtentTests(unittest.TestCase):
    def test_local_slope_drift_cannot_truncate_an_observed_longer_seam(self):
        lab,points,_=self.scene();points=np.array(points)
        anchors=[(-.03,65.85,80,440),(0,100,80,500)]
        before=_band_extent(points,anchors,lab)
        self.assertLess(before[1],400)
        _,after=_refine_truncated_seam(points,anchors,lab,before)
        self.assertAlmostEqual(after[1],500,delta=5)
        self.assertGreater(after[2]['end_cap_strength'][1],15)
        self.assertEqual(after[2]['slope_refinement']['independent_seam_end'],500)

    def scene(self):
        lab=np.full((160,600,3),110,np.uint8)
        lab[60:101,80:500]=(180,145,160)
        lab[60:101,300:500]=(160,180,125)  # Internal cover colour change.
        points=[[150,70],[240,70],[240,90],[150,90]]
        # Fragmented opposite seams deliberately disagree about the right end.
        lines=[[80,60,440,60],[85,100,310,100]]
        return lab,points,lines

    def test_fragmented_seams_recover_full_width_past_internal_colour_change(self):
        lab,points,lines=self.scene()
        box,poly,audit=restore_flat_extent(points,[80,60,590,100],None,lines,lab.shape,lab)
        self.assertEqual(audit['status'],'seam_extent')
        self.assertEqual(audit['continuation']['method'],'paired_seam_continuation')
        self.assertAlmostEqual(box[0],80,delta=4)
        self.assertAlmostEqual(box[2],500,delta=4)
        self.assertIsNotNone(poly)

    def test_line_fragments_without_pixel_support_cannot_authorize_extent(self):
        lab,points,lines=self.scene();lab[:]=110
        _,_,audit=restore_flat_extent(points,[80,60,590,100],None,lines,lab.shape,lab)
        self.assertEqual(audit['status'],'end_disagreement')

    def test_missing_seam_cannot_authorize_extent(self):
        lab,points,lines=self.scene()
        _,_,audit=restore_flat_extent(points,[80,60,590,100],None,lines[:1],lab.shape,lab)
        self.assertEqual(audit['status'],'insufficient_seams')

    def test_closer_crossing_line_cannot_truncate_the_spine(self):
        lab,points,lines=self.scene()
        lines.append([80,87.1,500,112.3])
        box,_,audit=restore_flat_extent(points,[80,60,590,100],None,lines,lab.shape,lab)
        self.assertEqual(audit['status'],'seam_extent')
        self.assertAlmostEqual(box[2],500,delta=4)
        self.assertAlmostEqual(audit['seams'][1][0],0.,delta=.01)

    def test_shadow_ridges_separate_same_colour_books(self):
        lab,points,lines=self.scene()
        lab[:]=150;lab[59:62,80:500]=50;lab[99:102,80:500]=50
        box,_,audit=restore_flat_extent(points,[80,60,590,100],None,lines,lab.shape,lab)
        self.assertEqual(audit['status'],'seam_extent')
        self.assertAlmostEqual(box[0],80,delta=5);self.assertAlmostEqual(box[2],500,delta=5)
