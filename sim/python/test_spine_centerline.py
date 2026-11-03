import unittest
import cv2
import numpy as np

from spine_centerline import refine_centerline_spine


class CenterlineTests(unittest.TestCase):
    def image(self, horizontal=False):
        image = np.full((460, 460, 3), 35, dtype=np.uint8)
        polygon = np.array([[160, 35], [230, 40], [245, 420], [155, 410]], np.int32)
        cv2.fillConvexPoly(image, polygon, (150, 200, 235))
        points = [[183, 170], [209, 170], [211, 245], [182, 245]]
        box = [160, 130, 240, 300]
        if horizontal:
            image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            points = [[459 - y, x] for x, y in points]
            box = [459 - box[3], box[0], 459 - box[1], box[2]]
        return image, points, box

    def test_vertical_short_text_does_not_define_book_height(self):
        image, points, old = self.image()
        box, polygon, audit = refine_centerline_spine(image, points, old)
        self.assertTrue(audit['accepted'], audit)
        self.assertLess(box[1], 55)
        self.assertGreater(box[3], 400)
        self.assertGreater(box[3] - box[1], 4 * 75)
        self.assertEqual(audit['anchor_semantics'], 'unknown_text_region')
        self.assertTrue(audit['semantic_selection_unchanged'])
        self.assertEqual(len(polygon), 4)

    def test_horizontal_and_perspective_sides(self):
        image, points, old = self.image(horizontal=True)
        box, polygon, audit = refine_centerline_spine(image, points, old)
        self.assertTrue(audit['accepted'], audit)
        self.assertLess(box[0], 60)
        self.assertGreater(box[2], 400)
        self.assertNotEqual(polygon[0][1], polygon[3][1])

    def test_tilted_ocr_axis_uses_oriented_roi(self):
        image, points, old = self.image()
        matrix = cv2.getRotationMatrix2D((230, 230), 7, 1)
        image = cv2.warpAffine(image, matrix, (460, 460), borderValue=(35, 35, 35))
        transform = lambda values: cv2.transform(np.asarray([values], np.float32), matrix)[0].tolist()
        points = transform(points)
        old_polygon = transform([[old[0], old[1]], [old[2], old[1]], [old[2], old[3]], [old[0], old[3]]])
        old_box = [min(p[0] for p in old_polygon), min(p[1] for p in old_polygon),
                   max(p[0] for p in old_polygon), max(p[1] for p in old_polygon)]
        box, polygon, audit = refine_centerline_spine(image, points, old_box, old_polygon)
        self.assertTrue(audit['accepted'], audit)
        self.assertGreater(box[3] - box[1], 300)
        self.assertGreater(abs(audit['axis'][0]), .05)

    def test_blank_image_exact_fallback(self):
        image, points, old = self.image()
        image[:] = 100
        old_polygon = [[160, 130], [240, 130], [240, 300], [160, 300]]
        box, polygon, audit = refine_centerline_spine(image, points, old, old_polygon)
        self.assertIs(box, old)
        self.assertIs(polygon, old_polygon)
        self.assertFalse(audit['accepted'])

    def test_crosswise_short_author_anchor_does_not_rotate_spine(self):
        image, _, old = self.image()
        author = [[180, 200], [215, 200], [215, 216], [180, 216]]
        box, _, audit = refine_centerline_spine(image, author, old)
        self.assertIs(box, old)
        self.assertFalse(audit['accepted'])
        self.assertEqual(audit['anchor_semantics'], 'unknown_text_region')

    def test_internal_broad_colour_change_is_not_an_end(self):
        image, points, old = self.image()
        # A publisher label changes the full interior, while both seams continue.
        cv2.rectangle(image, (171, 280), (228, 310), (40, 90, 160), -1)
        box, _, audit = refine_centerline_spine(image, points, old)
        self.assertTrue(audit['accepted'], audit)
        self.assertGreater(box[3], 400)

    def test_side_contrast_interruption_cannot_cut_previous_extent(self):
        image, points, _ = self.image()
        old = [155, 35, 245, 420]
        # An occlusion/label can destroy both seam contrasts temporarily, but
        # this does not establish that the physical book ends at that label.
        image[340:365, :] = 35
        box, _, audit = refine_centerline_spine(image, points, old)
        self.assertIs(box, old)
        self.assertFalse(audit['accepted'])
        self.assertEqual(audit['reason'], 'large_extent_contraction_requires_review')

    def test_unstable_invalid_geometry_keeps_existing(self):
        image, points, old = self.image()
        for malformed in ([[1, 2]], [[1, 2], [3, 4], [5, 6], [float('nan'), 8]]):
            box, _, audit = refine_centerline_spine(image, malformed, old)
            self.assertIs(box, old)
            self.assertFalse(audit['accepted'])


if __name__ == '__main__':
    unittest.main()
