"""Geometry regressions: internal labels and another tier are not book edges."""
import unittest
import cv2
import numpy as np
from spine_geometry import refine_spine, refine_flat_spine, spine_edges


class SpineGeometryTests(unittest.TestCase):
    def scene(self, multicolour=False):
        image = np.full((960, 320, 3), 180, np.uint8)
        cv2.rectangle(image, (80, 50), (160, 500), (45, 100, 30), -1)
        if multicolour:
            cv2.rectangle(image, (80, 50), (160, 280), (100, 190, 210), -1)
            cv2.rectangle(image, (80, 281), (160, 449), (190, 120, 60), -1)
        cv2.rectangle(image, (98, 450), (145, 487), (225, 225, 225), -1)
        cv2.rectangle(image, (80, 700), (160, 920), (35, 40, 65), -1)
        return image

    def test_bottom_stops_before_next_tier_and_preserves_label(self):
        for multicolour in (False, True):
            with self.subTest(multicolour=multicolour):
                image = self.scene(multicolour)
                box, polygon = refine_spine(spine_edges(image), (100, 100, 135, 360),
                                            [80, 50, 160, 921], image.shape)
                self.assertGreaterEqual(box[3], 495)
                self.assertLessEqual(box[3], 505)
                self.assertLess(box[1], 100)
                self.assertIsNotNone(polygon)

    def test_missing_edges_preserve_baseline(self):
        image = np.full((300, 200, 3), 180, np.uint8)
        baseline = [60, 20, 120, 280]
        box, polygon = refine_spine(spine_edges(image), (80, 80, 100, 180), baseline, image.shape)
        self.assertEqual(box, baseline)
        self.assertIsNone(polygon)

    def test_flat_clipped_spine_uses_visible_frame(self):
        image = np.full((320, 600, 3), 180, np.uint8)
        cv2.rectangle(image, (0, 80), (599, 160), (45, 100, 30), -1)
        points = [[100, 100], [350, 100], [350, 135], [100, 135]]
        box, polygon = refine_flat_spine(image, points, [50, 50, 500, 200])
        self.assertEqual(box[0], 0)
        self.assertEqual(box[2], 599)
        self.assertLessEqual(abs(box[1] - 80), 3)
        self.assertLessEqual(abs(box[3] - 160), 3)
        self.assertIsNotNone(polygon)


if __name__ == '__main__':
    unittest.main()
