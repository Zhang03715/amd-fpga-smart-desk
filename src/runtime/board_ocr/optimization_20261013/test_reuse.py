import itertools
import unittest
import numpy as np

from expanded_title_review import use_expanded_text
from board_ocr.optimization_20261013.reuse import expansion_can_change_selection, scan_with_crops


class FakeEngine:
    text_score = .5

    def __init__(self, *, transform=False, fail=False):
        self.transform, self.fail = transform, fail
        self.points = np.asarray([[[0, 0], [8, 0], [8, 4], [0, 4]],
                                  [[0, 8], [8, 8], [8, 12], [0, 12]]], np.float32)
        self.get_crop_img_list = lambda image, boxes: [image[:4, :8].copy(), image[8:12, :8].copy()]
        self.text_cls = lambda images: ([255-i for i in images], [], .01)

    def filter_result(self, boxes, results):
        return ([b for b,r in zip(boxes,results) if r[1] >= self.text_score],
                [r for r in results if r[1] >= self.text_score])

    def __call__(self, image):
        crops = self.get_crop_img_list(image.copy() if self.transform else image, self.points)
        classified,_,_ = self.text_cls(crops)
        if self.fail:
            raise RuntimeError('failed inference')
        boxes, results = self.filter_result(self.points, [('reject',.3),('title',.99)])
        return [[box.tolist(), text, conf] for box,(text,conf) in zip(boxes,results)], [1.,.1,.1]


class ReuseTests(unittest.TestCase):
    def test_skip_implies_selection_impossible_exhaustive_small_titles(self):
        words = [''.join(chars) for n in range(5) for chars in itertools.product('ab', repeat=n)]
        for original in words:
            for target in words:
                if not expansion_can_change_selection(original, target):
                    self.assertFalse(use_expanded_text(original, target, .99, target))
        self.assertTrue(expansion_can_change_selection('高等数学', None))
        self.assertTrue(expansion_can_change_selection('工智能概论', '人工智能概论'))
        self.assertFalse(expansion_can_change_selection('应用平册', '应用手册'))
        self.assertFalse(expansion_can_change_selection('高等数学', '高等数学'))

    def test_crop_mapping_preserves_low_confidence_filter_and_restores_hooks(self):
        engine = FakeEngine()
        image = np.arange(16*8*3, dtype=np.uint8).reshape(16,8,3)
        old = engine.get_crop_img_list, engine.text_cls, engine.filter_result
        rows,_,crops = scan_with_crops(engine,image)
        self.assertEqual(len(rows),1)
        np.testing.assert_array_equal(crops[0],255-image[8:12,:8])
        self.assertEqual((engine.get_crop_img_list,engine.text_cls,engine.filter_result),old)

    def test_global_resize_or_failure_cannot_reuse_stale_crops(self):
        image = np.zeros((16,8,3),np.uint8)
        engine = FakeEngine(transform=True)
        _,_,crops = scan_with_crops(engine,image)
        self.assertIsNone(crops)
        engine = FakeEngine(fail=True)
        old = engine.get_crop_img_list,engine.text_cls,engine.filter_result
        with self.assertRaisesRegex(RuntimeError,'failed inference'):
            scan_with_crops(engine,image)
        self.assertEqual((engine.get_crop_img_list,engine.text_cls,engine.filter_result),old)


if __name__ == '__main__':
    unittest.main()
