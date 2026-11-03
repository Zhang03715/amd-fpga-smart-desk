"""Request-local geometry reuse must preserve evidence and capture boundaries."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from hybrid_book_locator import GeometryContext, locate, locate_spine


class GeometryCacheTests(unittest.TestCase):
    def test_context_is_lazy_bounded_and_rejects_other_capture(self):
        first = np.full((120, 180, 3), 50, np.uint8)
        second = np.full_like(first, 190)
        context = GeometryContext(first)
        self.assertEqual(context.retained_bytes, 0)
        rotated = context.rotated
        self.assertIs(rotated, context.rotated)
        self.assertEqual(context.audit['rotation_calls'], 1)
        self.assertIs(context.blurred_lab(first), context.blurred_lab(first))
        with self.assertRaisesRegex(ValueError, 'different capture'):
            context.blurred_lab(second)
        other = GeometryContext(second)
        self.assertFalse(np.array_equal(context.blurred_lab(first), other.blurred_lab(second)))
        self.assertEqual(other.audit['lab_blur_calls'], 1)

    def test_vertical_and_flat_boxes_exact_and_shared_preprocessing(self):
        image = np.full((220, 320, 3), 200, np.uint8)
        image[20:95, 35:280] = (80, 110, 160)
        image[100:185, 30:290] = (150, 70, 80)
        flat = [[80, 40], [220, 40], [220, 60], [80, 60]]
        upright = [[80, 45], [100, 45], [100, 165], [80, 165]]
        context = GeometryContext(image)
        for points in (flat, flat, upright):
            self.assertEqual(locate_spine(image, points, [30, 290]),
                             locate_spine(image, points, [30, 290], context=context))
        self.assertEqual(context.audit, dict(rotation_calls=1, rotated_boundary_calls=1, lab_blur_calls=2))

    def test_same_process_different_frames_and_default_remains_compatible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for n, background in enumerate((100, 200)):
                image = np.full((220, 320, 3), background, np.uint8)
                image[30:100, 25+n*12:280-n*12] = (30, 80, 120)
                path = root / f'{n}.png'
                self.assertTrue(cv2.imwrite(str(path), image))
                ocr = [[[[80, 45], [210, 45], [210, 70], [80, 70]], 'title', .99]]
                audit = {}
                locate(path, 'title', root / f'old{n}', 1., draw_labels=False, supplied_ocr=ocr)
                locate(path, 'title', root / f'new{n}', 1., draw_labels=False, supplied_ocr=ocr,
                       geometry_cache=True, geometry_audit=audit)
                filename = f'{n}_hybrid.json'
                self.assertEqual(json.loads((root/f'old{n}'/filename).read_text()),
                                 json.loads((root/f'new{n}'/filename).read_text()))
                self.assertEqual(audit['scope'], 'one_capture_only')
                self.assertEqual(audit['rotation_calls'], 1)


if __name__ == '__main__':
    unittest.main()
