import unittest
import cv2
import numpy as np
from spine_cap_edges import refine_supported_caps


class CapEdgeTests(unittest.TestCase):
    def setUp(self):
        self.mask=np.zeros((250,150),np.uint8)
        self.mask[10:40,50:90]=1
        self.mask[40:230,40:100]=1
        self.image=np.full((250,150,3),30,np.uint8)
        self.image[40:230,40:100]=(80,140,190)
        self.quad=np.asarray([[40,10],[99,10],[99,229],[40,229]],np.float32)
        self.title=[[55,70],[80,70],[80,160],[55,160]]

    def test_narrow_cap_with_body_color_edge_is_trimmed(self):
        quad,audit=refine_supported_caps(self.image,self.mask,self.quad,[self.title])
        self.assertTrue(audit['applied'])
        self.assertTrue(np.all((quad[:2,1]>=37)&(quad[:2,1]<=43)))
        np.testing.assert_allclose(quad[2:],self.quad[2:],atol=1e-4)

    def test_color_band_without_narrow_protrusion_does_not_trim(self):
        mask=self.mask.copy();mask[10:230,40:100]=1
        quad,audit=refine_supported_caps(self.image,mask,self.quad,[self.title])
        self.assertFalse(audit['applied'])
        np.testing.assert_array_equal(quad,self.quad)

    def test_narrow_cap_without_image_edge_does_not_trim(self):
        quad,audit=refine_supported_caps(np.full_like(self.image,100),self.mask,self.quad,[self.title])
        self.assertFalse(audit['applied'])

    def test_label_hole_does_not_count_as_narrow_silhouette(self):
        mask=np.zeros_like(self.mask);mask[10:230,40:100]=1
        mask[15:40,45:95]=0
        quad,audit=refine_supported_caps(self.image,mask,self.quad,[self.title])
        self.assertFalse(audit['applied'])

    def test_group_text_in_cap_prevents_trim(self):
        quad,audit=refine_supported_caps(self.image,self.mask,self.quad,
                                       [self.title,[[55,15],[85,15],[85,35],[55,35]]])
        self.assertFalse(audit['applied'])
        self.assertEqual(audit['reason'],'would_trim_group_text')

    def test_flat_book_is_unchanged(self):
        image=cv2.rotate(self.image,cv2.ROTATE_90_CLOCKWISE)
        mask=cv2.rotate(self.mask,cv2.ROTATE_90_CLOCKWISE)
        quad=np.column_stack((249-self.quad[:,1],self.quad[:,0])).astype(np.float32)
        result,audit=refine_supported_caps(image,mask,quad)
        self.assertFalse(audit['applied'])
        self.assertEqual(audit['reason'],'not_upright_front_cap')

    def test_frame_clipped_side_cannot_define_cap_width(self):
        quad=self.quad.copy();quad[:,0]-=40
        result,audit=refine_supported_caps(self.image,self.mask,quad)
        self.assertFalse(audit['applied'])
        self.assertEqual(audit['reason'],'short_axis_side_clipped_by_frame')


if __name__=='__main__':
    unittest.main()
