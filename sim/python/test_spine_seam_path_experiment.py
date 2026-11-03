import unittest
import numpy as np
from spine_seam_path_experiment import trace_side, propose_visible_extension, supported_interior_endcap


class ContinuousSeamTests(unittest.TestCase):
    def test_internal_colour_band_does_not_override_later_supported_endcap(self):
        samples=[dict(position=x,side_strengths=[30,30] if x<160 else [0,0],
                      transverse_support=1. if x in (105,150) else 0.,
                      transverse_median=250. if x==105 else 80. if x==150 else 0.) for x in range(100,200)]
        result=supported_interior_endcap(samples,30,100)
        self.assertEqual(result['endpoint'],150)

    def test_single_side_loss_cannot_create_endcap(self):
        samples=[dict(position=x,side_strengths=[0,30],transverse_support=1.,
                      transverse_median=200.) for x in range(100,200)]
        self.assertEqual(supported_interior_endcap(samples,30,100)['status'],'no_sustained_paired_side_loss')

    def test_short_side_gap_does_not_create_endcap(self):
        samples=[dict(position=x,side_strengths=[0,0] if 150<=x<155 else [30,30],
                      transverse_support=1.,transverse_median=100.) for x in range(100,200)]
        self.assertEqual(supported_interior_endcap(samples,30,100)['status'],'no_sustained_paired_side_loss')

    def test_generic_extension_rotates_back_to_original_image(self):
        import cv2
        image=np.zeros((90,180,3),np.uint8)
        image[30:60]=180
        polygon=np.asarray([[0,30],[90,30],[90,60],[0,60]],float)
        mask,audit=propose_visible_extension(image,polygon)
        self.assertIsNotNone(mask)
        self.assertFalse(audit['accepted_for_production'])
        self.assertTrue(mask[45,170])
        rotated=cv2.rotate(image,cv2.ROTATE_90_CLOCKWISE)
        rotated_polygon=np.column_stack([image.shape[0]-1-polygon[:,1],polygon[:,0]])
        other,_=propose_visible_extension(rotated,rotated_polygon)
        self.assertIsNotNone(other)
        np.testing.assert_array_equal(mask,cv2.rotate(other.astype(np.uint8),cv2.ROTATE_90_COUNTERCLOCKWISE)>0)

    def test_generic_extension_rejects_sides_ending_inside_image(self):
        image=np.zeros((90,180,3),np.uint8)
        image[30:60,:100]=180
        mask,audit=propose_visible_extension(image,[[0,30],[90,30],[90,60],[0,60]])
        self.assertIsNone(mask)
        self.assertEqual(audit['status'],'insufficient_continuous_side_support')

    def test_continuous_edge_beats_isolated_strong_spur(self):
        image=np.full((80,160,3),120,np.uint8)
        image[40:]=180
        image[22:26,65:76]=0
        result=trace_side(image,(8,40),150,0,80)
        self.assertEqual(result['status'],'diagnostic_path_only')
        self.assertGreater(result['supported_fraction'],.95)
        self.assertTrue(all(abs(y-40)<=3 for _,y in result['path']))

    def test_blank_image_records_missing_support(self):
        result=trace_side(np.zeros((80,160,3),np.uint8),(8,40),150,0,40)
        self.assertEqual(result['supported_fraction'],0)
        self.assertEqual(result['longest_weak_run_samples'],len(result['path']))

    def test_frame_exit_is_unknown_not_clamped_boundary(self):
        result=trace_side(np.zeros((80,160,3),np.uint8),(8,60),150,.5,40)
        self.assertEqual(result['status'],'prior_exits_frame')
        self.assertFalse(result['path'])


if __name__=='__main__':
    unittest.main()
