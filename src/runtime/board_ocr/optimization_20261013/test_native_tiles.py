import unittest
import numpy as np
from .native_tiles import windows,detect,select_margin


class TileTests(unittest.TestCase):
    def test_margin_cannot_change_title_or_lower_acceptance_threshold(self):
        self.assertTrue(select_margin('马克思主义基本原理',.86,'马克思主义基本原理',.92))
        self.assertFalse(select_margin('马克思主义基本原理',.86,'马克思主义基本原埋',.99))
        self.assertFalse(select_margin('马克思主义基本原理',.86,'马克思主义基本原理',.89))
        self.assertFalse(select_margin('原理',.86,'原理',.99))
    def test_windows_cover_original_roi_with_overlap(self):
        tiles=windows(1920,1080,[600,0,1920,1080])
        self.assertEqual(tiles,[[600,0,1560,1080],[960,0,1920,1080]])
        self.assertEqual(windows(1920,1080,[300,0,1920,1080]),[[300,0,1260,1080],[960,0,1920,1080]])
        with self.assertRaises(ValueError):windows(100,100,[0,0,101,100])

    def test_detection_restores_coordinates_deduplicates_and_restores_model(self):
        class Detector:
            mean=std=[.5]*3
            def get_preprocess(self,size):return 'original'
            def __call__(self,image):
                # Same full-frame word appears in each overlapping window.
                self.calls=getattr(self,'calls',0)+1
                x=600 if self.calls==1 else 240
                return np.array([[[x,800],[x+180,800],[x+180,820],[x,820]]],dtype=np.float32),.1
        d=Detector();original=d.get_preprocess
        boxes,audit=detect(np.zeros((1080,1920,3),dtype=np.uint8),d,[],[600,0,1920,1080])
        self.assertEqual(len(boxes),1)
        self.assertEqual(boxes[0][0].tolist(),[1200,800])
        self.assertEqual(d.get_preprocess,original)
        self.assertEqual(audit['unique_boxes'],1)


if __name__=='__main__':unittest.main()
