from copy import deepcopy
import json
from pathlib import Path
import unittest
import cv2
import numpy as np

from spine_groups import group_spine_regions


ROOT = Path(__file__).resolve().parent


def record(box, title, text='text'):
    x1, y1, x2, y2 = box
    return dict(text=text, book_box=box, spine_polygon=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                title_box=title, ocr_confidence=.98, orientation='flat')


def title(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


class SpineGroupsTests(unittest.TestCase):
    def test_short_crosswise_label_cannot_anchor_a_strip_across_books(self):
        rows = [record([20, 10, 65, 330], title(32, 40, 48, 190)),
                record([70, 10, 115, 330], title(82, 40, 98, 190)),
                record([20, 298, 315, 328], title(32, 306, 48, 318), 'label')]
        result = group_spine_regions(None, rows, crosswise_cleanup=True)
        self.assertEqual([s['region_ids'] for s in result['spines']], [[0, 2], [1]])
        self.assertEqual(result['spines'][0]['book_box'], rows[0]['book_box'])

    def test_publisher_fragment_attaches_without_expanding_full_book(self):
        rows = [record([20, 10, 65, 330], title(32, 40, 48, 190)),
                record([70, 10, 115, 330], title(82, 40, 98, 190)),
                record([20, 225, 80, 330], title(32, 250, 48, 302), 'publisher')]
        result = group_spine_regions(None, rows, crosswise_cleanup=True)
        self.assertEqual([s['region_ids'] for s in result['spines']], [[0, 2], [1]])
        self.assertEqual(result['spines'][0]['book_box'], rows[0]['book_box'])

    def test_full_upright_labels_preserved_without_horizontal_inventory(self):
        path = ROOT/'output/ocr-link-server/pc-upright-a-grouped-20261013-01/response.json'
        if not path.is_file():
            self.skipTest('local full upright evidence unavailable')
        rows = json.loads(path.read_text(encoding='utf-8'))['result']['matches']
        result = group_spine_regions(None, rows, crosswise_cleanup=True)
        self.assertEqual(len(result['regions']), len(rows))
        self.assertTrue(all(s['book_box'][3]-s['book_box'][1] > s['book_box'][2]-s['book_box'][0]
                            for s in result['spines']))
        publisher = result['regions'][23]['spine_group_id']
        self.assertEqual(publisher, result['regions'][14]['spine_group_id'])
        self.assertIsNotNone(publisher)

    def test_same_book_colour_blocks_and_multiple_texts_one_hypothesis(self):
        image = np.zeros((160, 650, 3), np.uint8)
        image[30:90, 20:620] = (180, 120, 40)
        image[30:90, 340:620] = (220, 225, 235)
        records = [record([20, 30, 620, 90], title(80, 40, 290, 70), 'title'),
                   record([300, 30, 630, 90], title(400, 45, 480, 70), 'edition'),
                   record([20, 30, 620, 90], title(520, 48, 590, 70), 'author')]
        untouched = deepcopy(records)
        result = group_spine_regions(image, records)
        self.assertEqual(result['audit']['book_hypotheses'], 1)
        self.assertEqual(result['spines'][0]['region_ids'], [0, 1, 2])
        self.assertEqual(result['spines'][0]['book_box'], [20, 30, 620, 90])
        self.assertEqual(records, untouched)
        for original, returned in zip(records, result['regions']):
            self.assertEqual({key: returned[key] for key in original}, original)

    def test_adjacent_same_colour_thin_books_not_merged(self):
        image = np.full((180, 320, 3), 100, np.uint8)
        records = [record([20, 30, 300, 70], title(50, 40, 130, 60)),
                   record([20, 69, 300, 110], title(55, 80, 140, 100)),
                   record([20, 109, 300, 150], title(55, 120, 140, 140))]
        result = group_spine_regions(image, records)
        self.assertEqual([spine['region_ids'] for spine in result['spines']], [[0], [1], [2]])

    def test_bad_cross_book_box_cannot_bridge_two_anchors(self):
        image = np.full((160, 280, 3), 100, np.uint8)
        records = [record([20, 30, 240, 80], title(50, 42, 120, 65)),
                   record([20, 80, 240, 130], title(50, 95, 120, 117)),
                   record([20, 30, 240, 130], title(80, 65, 150, 95), 'bad_bridge')]
        result = group_spine_regions(image, records)
        self.assertEqual([spine['region_ids'] for spine in result['spines']], [[0], [1]])
        self.assertIsNone(result['regions'][2]['spine_group_id'])
        self.assertEqual(result['audit']['unresolved_region_ids'], [2])
        # Even when the bridge's OCR belongs clearly to just the upper book,
        # its bad physical box must not replace that book's narrow canonical.
        records[2]['title_box'] = title(80, 42, 150, 65)
        result = group_spine_regions(image, records)
        self.assertEqual([spine['region_ids'] for spine in result['spines']], [[0], [1]])
        self.assertEqual(result['spines'][0]['book_box'], records[0]['book_box'])
        self.assertIsNone(result['regions'][2]['spine_group_id'])

    def test_no_transitive_closure_along_overlapping_chain(self):
        records = [record([0, 20, 200, 60], title(30, 30, 50, 48)),
                   record([60, 20, 260, 60], title(130, 30, 150, 48)),
                   record([120, 20, 320, 60], title(230, 30, 250, 48))]
        result = group_spine_regions(None, records)
        self.assertEqual(len(result['spines']), 2)
        self.assertNotIn([0, 1, 2], [spine['region_ids'] for spine in result['spines']])

    def test_crosswise_small_text_unique_containment_not_new_book(self):
        records = [record([20, 30, 300, 100], title(50, 45, 200, 70)),
                   record([220, 40, 245, 80], title(227, 45, 240, 75), 'publisher'),
                   record([250, 40, 275, 80], title(255, 45, 265, 75), 'tiny_author')]
        result = group_spine_regions(None, records)
        self.assertEqual([spine['region_ids'] for spine in result['spines']], [[0, 1, 2]])
        self.assertEqual(result['spines'][0]['representative_region_id'], 0)

    def test_disjoint_end_to_end_books_not_merged_by_colour_or_axis(self):
        records = [record([20, 30, 220, 80], title(40, 40, 180, 65)),
                   record([220, 30, 420, 80], title(245, 40, 385, 65))]
        result = group_spine_regions(None, records)
        self.assertEqual([spine['region_ids'] for spine in result['spines']], [[0], [1]])

    def test_live_d_texts_aggregate_without_changing_transcriptions(self):
        path = ROOT / 'output/ocr-link-server/z2-scan-d-20261013-01/pipeline/input_hybrid.json'
        if not path.is_file():
            self.skipTest('local captured OCR evidence unavailable')
        records = json.loads(path.read_text(encoding='utf8'))
        image = cv2.imread(str(ROOT / 'captures/new_flat_20261008/shelf_flat_d.jpg'))
        result = group_spine_regions(image, records)
        self.assertEqual([spine['region_ids'] for spine in result['spines']],
                         [[0, 1, 2], [3, 4, 5], [6], [7, 8], [9, 10, 11], [12, 13], [14, 15]])
        self.assertEqual(result['audit']['text_regions'], 16)
        self.assertEqual(result['audit']['book_hypotheses'], 7)
        self.assertEqual([r['text'] for r in result['regions']], [r['text'] for r in records])
        self.assertEqual(result['audit']['unresolved_region_ids'], [])
        for spine in result['spines']:
            original = records[spine['representative_region_id']]
            self.assertEqual(spine['book_box'], original['book_box'])

    def test_historical_selected_a_b_c_adjacent_spines_stay_separate(self):
        cases = json.loads((ROOT / 'board_ocr/optimization_20261013/geometry_cases.json').read_text(encoding='utf8'))
        for case in cases[:3]:
            with self.subTest(case=case['name']):
                path = (ROOT / 'board_ocr/optimization_20261013/results/geometry_host' / case['name'] / '0_legacy'
                        / (Path(case['image']).stem + '_hybrid.json'))
                if not path.is_file():
                    continue
                records = json.loads(path.read_text(encoding='utf8'))
                result = group_spine_regions(cv2.imread(str(ROOT / case['image'])), records)
                self.assertEqual([s['region_ids'] for s in result['spines']], [[i] for i in range(len(records))])
                self.assertEqual(result['audit']['count_semantics'], 'book_hypotheses_not_proven_inventory')


if __name__ == '__main__':
    unittest.main()
