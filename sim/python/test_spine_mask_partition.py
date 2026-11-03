import unittest
import numpy as np
from spine_mask_partition import partition_neighbour_mask,extension_evidence,extend_quad_ends
from sam_spine_experiment import validate_mask


class MaskPartitionTests(unittest.TestCase):
    def test_extension_preserves_unextended_top_instead_of_refitting_it(self):
        old=[[20,20],[60,20],[60,150],[20,150]]
        proposal=[[22,25],[60,25],[60,190],[22,190]]
        quad,audit=extend_quad_ends(old,proposal)
        self.assertIsNotNone(quad)
        self.assertEqual(set(map(tuple,quad.tolist())),{(20,20),(60,20),(60,190),(22,190)})

    def test_composed_extension_still_rejects_neighbour_overlap(self):
        old=[[20,20],[60,20],[60,150],[20,150]]
        proposal=[[20,20],[60,20],[75,190],[20,190]]
        quad,audit=extend_quad_ends(old,proposal,neighbour_boxes=[[[62,170],[78,170],[78,190],[62,190]]])
        self.assertIsNone(quad)
        self.assertEqual(audit['reason'],'extension_quad_text_conflict')

    def test_extension_gate_accepts_length_and_rejects_width_inflation(self):
        baseline=np.zeros((220,160),bool);baseline[40:160,30:70]=True
        longer=baseline.copy();longer[160:190,30:70]=True
        self.assertTrue(extension_evidence(baseline,longer)['eligible_extension'])
        wider=longer.copy();wider[40:190,70:100]=True
        self.assertFalse(extension_evidence(baseline,wider)['eligible_extension'])

    def test_extension_gate_rejects_loss_of_original_body(self):
        baseline=np.zeros((220,160),bool);baseline[40:160,30:70]=True
        shifted=np.zeros_like(baseline);shifted[40:190,35:75]=True
        self.assertFalse(extension_evidence(baseline,shifted)['eligible_extension'])

    def setUp(self):
        self.image=np.zeros((200,200,3),np.uint8)
        self.image[10:190,20:80]=(160,90,50)
        self.image[10:190,80:140]=(30,180,200)
        self.mask=np.zeros((200,200),bool);self.mask[10:190,20:140]=True
        self.points=np.asarray([[45,60],[45,90],[45,120],[105,90]],float)
        self.labels=np.asarray([1,1,1,0])
        self.title=[[35,40],[55,40],[55,140],[35,140]]
        self.neighbour=[[95,40],[115,40],[115,140],[95,140]]

    def test_split_follows_color_seam_and_passes_original_guard(self):
        part,audit=partition_neighbour_mask(self.image,self.mask,self.points,self.labels,
                                           [self.title],[self.neighbour])
        self.assertTrue(audit['proposed'])
        self.assertFalse(np.any(part&~self.mask))
        self.assertFalse(part[90,105])
        result,validation=validate_mask(part,self.points,self.labels,self.title,[self.neighbour],[self.title])
        self.assertIsNotNone(result)
        self.assertTrue(validation['eligible'])
        self.assertLessEqual(validation['book_box'][2],80)

    def test_partition_is_not_created_without_neighbour_evidence(self):
        part,audit=partition_neighbour_mask(self.image,self.mask,self.points,self.labels,[self.title],[])
        self.assertIsNone(part)
        self.assertEqual(audit['reason'],'no_neighbour_text_inside_mask')

    def test_conflicting_text_seeds_are_rejected(self):
        part,audit=partition_neighbour_mask(self.image,self.mask,self.points,self.labels,[self.title],[self.title])
        self.assertIsNone(part)
        self.assertEqual(audit['reason'],'conflicting_ocr_seeds')

    def test_positive_seed_hole_is_not_filled_to_force_acceptance(self):
        mask=self.mask.copy();mask[90,45]=False
        part,audit=partition_neighbour_mask(self.image,mask,self.points,self.labels,[self.title],[self.neighbour])
        self.assertIsNone(part)
        self.assertEqual(audit['reason'],'positive_seed_conflict')

    def test_existing_foreground_seed_preserves_two_color_book_body(self):
        image=self.image.copy()
        image[130:190,20:80]=(210,150,70)
        baseline=np.zeros_like(self.mask);baseline[11:150,21:79]=True
        part,audit=partition_neighbour_mask(image,self.mask,self.points,self.labels,
                                           [self.title],[self.neighbour],foreground_seed=baseline)
        self.assertTrue(audit['proposed'])
        # Known interior pixels remain foreground even across a printed band.
        self.assertTrue(part[140,45])
        self.assertFalse(np.any(part&~self.mask))

    def test_foreground_seed_cannot_override_other_title_evidence(self):
        baseline=self.mask.copy()
        part,audit=partition_neighbour_mask(self.image,self.mask,self.points,self.labels,
                                           [self.title],[self.neighbour],foreground_seed=baseline)
        self.assertIsNone(part)
        self.assertEqual(audit['reason'],'conflicting_ocr_seeds')

    def test_expanded_neighbour_seed_can_reassign_prior_border(self):
        baseline=np.zeros_like(self.mask);baseline[10:190,20:76]=True
        neighbour=[[70,40],[90,40],[90,140],[70,140]]
        part,audit=partition_neighbour_mask(self.image,self.mask,self.points,self.labels,
            [self.title],[neighbour],foreground_seed=baseline,expanded_neighbour_seeds=True)
        self.assertIsNotNone(part)
        self.assertGreater(audit['reassigned_foreground_seed_pixels'],0)
        self.assertFalse(np.any(part&~self.mask))

    def test_expanded_neighbour_seed_cannot_override_current_text(self):
        part,audit=partition_neighbour_mask(self.image,self.mask,self.points,self.labels,
            [self.title],[self.title],foreground_seed=self.mask,expanded_neighbour_seeds=True)
        self.assertIsNone(part)
        self.assertEqual(audit['reason'],'conflicting_ocr_seeds')

    def test_roi_partition_maps_back_to_original_coordinates(self):
        points=np.vstack((self.points,[[190,195]]));labels=np.append(self.labels,0)
        full,_=partition_neighbour_mask(self.image,self.mask,points,labels,[self.title],[self.neighbour])
        cropped,audit=partition_neighbour_mask(self.image,self.mask,points,labels,[self.title],[self.neighbour],crop_to_mask=True)
        np.testing.assert_array_equal(cropped,full)
        self.assertLess(audit['working_shape'][1],self.mask.shape[1])
        self.assertEqual(cropped.shape,self.mask.shape)

    def test_empty_roi_mask_is_rejected(self):
        part,audit=partition_neighbour_mask(self.image,np.zeros_like(self.mask),self.points,self.labels,
            [self.title],[self.neighbour],crop_to_mask=True)
        self.assertIsNone(part)
        self.assertEqual(audit['reason'],'empty_mask')


if __name__=='__main__':
    unittest.main()
