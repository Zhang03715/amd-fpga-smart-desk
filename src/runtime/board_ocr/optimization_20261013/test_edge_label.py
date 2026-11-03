import unittest
import numpy as np
from .edge_label import span,select,clipped_points


class EdgeLabelTests(unittest.TestCase):
    def test_only_small_coloured_edge_block_is_separated(self):
        im=np.full((30,330,3),190,np.uint8);im[5:25,2:60]=(90,90,170)
        interval=span(im);self.assertIsNotNone(interval);self.assertLess(interval[0],65)
        self.assertGreater(interval[0],55);self.assertEqual(interval[1],330)
        im[:]=(90,90,170);self.assertIsNone(span(im))

    def test_no_target_specific_correction_or_short_title_clipping(self):
        self.assertTrue(select('C++程序设计思想与方法目',.92,'C++程序设计思想与方法',.98))
        self.assertFalse(select('C++程序设计思恩与方法目',.92,'C++程序设计思想与方法',.99))
        self.assertFalse(select('大学物理实验教程',.9,'大学物理实验',.99))
        self.assertFalse(select('C++程序设计思想与方法目',.92,'C++程序设计思想与方法',.94))
        self.assertTrue(select('C++程序设计思与方法日目',.90,'C++程序设计思想与方法',.96,('C++程序设计思想与方法',.94)))
        self.assertFalse(select('C++程序设计思与方法日目',.90,'C++程序设计思想与方法',.96,('C++程序设计思恩与方法',.99)))

    def test_trim_coordinates_follow_both_crop_orientations(self):
        self.assertEqual(clipped_points([[0,0],[100,0],[100,20],[0,20]],10,90,100),
                         [[10,0],[90,0],[90,20],[10,20]])
        self.assertEqual(clipped_points([[0,0],[20,0],[20,100],[0,100]],10,90,100),
                         [[0,10],[20,10],[20,90],[0,90]])
