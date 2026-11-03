import json
from pathlib import Path
import unittest
import cv2
import numpy as np
from upright_geometry import refine_upright_records, supported_endcaps
from spine_groups import group_spine_regions

ROOT = Path(__file__).resolve().parent


class UprightGeometryTests(unittest.TestCase):
    def test_clipped_b_headers_are_three_books_and_preserve_text(self):
        source = ROOT/'output/ocr-link-server/pc-multi-b-grouped-v2-20261014-01'
        if not (source/'response.json').exists():
            self.skipTest('captured local GPU evidence unavailable')
        rows=json.loads((source/'response.json').read_text(encoding='utf-8'))['result']['matches']
        image=cv2.imread(str(source/'input.jpg'))
        refined=refine_upright_records(image,rows)
        grouped=group_spine_regions(image,refined,crosswise_cleanup=True)
        first=grouped['regions'][10]['spine_group_id']
        second=grouped['regions'][11]['spine_group_id']
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first,second)
        self.assertEqual(first,grouped['regions'][12]['spine_group_id'])
        self.assertEqual(second,grouped['regions'][13]['spine_group_id'])
        for i in (10,11,12,13):
            self.assertEqual(refined[i]['text'],rows[i]['text'])
            self.assertTrue(refined[i]['visible_region_clipped'])

    def test_flat_d_geometry_is_unchanged(self):
        source=ROOT/'output/ocr-link-server/z2-scan-d-20261013-01'
        if not (source/'response.json').exists():
            self.skipTest('captured local GPU evidence unavailable')
        rows=json.loads((source/'response.json').read_text(encoding='utf-8'))['result']['matches']
        refined=refine_upright_records(cv2.imread(str(source/'input.jpg')),rows)
        self.assertEqual(refined,rows)

    def test_neighbouring_tall_book_does_not_hide_short_book_bottom(self):
        lab = np.full((300, 200, 3), 210, np.uint8)
        lab[20:200,40:120] = (100,150,170)
        lab[20:270,120:190] = (45,150,200)
        lab[150:175,55:105] = (210,128,128)
        horizontal = np.asarray([[55,150,105,150], [40,200,120,200],
                                 [20,280,190,280]], dtype=np.float32)
        box, audit = supported_endcaps((np.empty((0,4)),horizontal,lab),
                                      (65,50,85,120),[40,20,120,280])
        # The symmetric six-pixel gradient proposal has a three-pixel
        # localisation radius; a label at 150 must still be rejected.
        self.assertLessEqual(abs(box[3]-200),3)
        self.assertTrue(audit['bottom_cap_supported'])

    def test_full_b_blue_book_stops_before_shelf_blank_band(self):
        source = ROOT/'output/ocr-link-server/pc-multi-b-grouped-v2-20261014-01'
        if not (source/'response.json').exists():
            self.skipTest('captured local GPU evidence unavailable')
        rows = json.loads((source/'response.json').read_text(encoding='utf-8'))['result']['matches']
        refined = refine_upright_records(cv2.imread(str(source/'input.jpg')),rows)
        self.assertTrue(730 <= refined[7]['book_box'][3] <= 750)
        self.assertEqual(refined[7]['text'],rows[7]['text'])

    def test_full_image_perspective_titles_recover_without_changing_ocr(self):
        source = ROOT/'output/ocr-link-server/pc-upright-a-grouped-20261013-01'
        if not (source/'response.json').exists():
            self.skipTest('captured local GPU evidence unavailable')
        rows = json.loads((source/'response.json').read_text(encoding='utf-8'))['result']['matches']
        image = cv2.imread(str(source/'input.jpg'))
        refined = refine_upright_records(image, rows)
        grouped = group_spine_regions(image, refined, crosswise_cleanup=True)
        for old, new in zip(rows, refined):
            for key in ('text', 'ocr_confidence', 'title_box', 'match_score'):
                self.assertEqual(old[key], new[key])
        # Six actual titles previously rejected due to neighbouring wide boxes.
        recovered = [3, 5, 12, 16, 19, 20]
        for index in recovered:
            self.assertIsNotNone(grouped['regions'][index]['spine_group_id'])
        self.assertEqual(len({grouped['regions'][i]['spine_group_id'] for i in recovered}), len(recovered))
        self.assertLess(refined[3]['book_box'][2]-refined[3]['book_box'][0],
                        rows[3]['book_box'][2]-rows[3]['book_box'][0])
        # Geometry experiment must never turn a small horizontal OCR into a
        # vertical book; its cleanup remains a separately selected experiment.
        self.assertEqual(rows[28]['book_box'], refined[28]['book_box'])


if __name__ == '__main__':
    unittest.main()
