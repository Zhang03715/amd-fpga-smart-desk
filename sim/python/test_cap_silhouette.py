import unittest
import cv2
import numpy as np
import json
from pathlib import Path
from cap_silhouette import refine_silhouette_caps,refine_silhouette_records


class SilhouetteTests(unittest.TestCase):
    def sample(self):
        image=np.full((360,180,3),210,np.uint8)
        image[45:310,55:115]=(45,65,135)
        cv2.putText(image,'ABC',(67,140),cv2.FONT_HERSHEY_SIMPLEX,.5,(220,230,235),1)
        cv2.rectangle(image,(65,265),(105,295),(245,245,245),-1)
        points=[[72,90],[94,90],[94,225],[72,225]]
        old=[55,0,115,340]
        return image,points,old

    def test_seeded_silhouette_recovers_caps_not_text_length(self):
        image,points,old=self.sample()
        box,poly,audit=refine_silhouette_caps(image,points,old,apply_candidates=True)
        self.assertTrue(audit['accepted'],audit)
        self.assertLess(abs(box[1]-45),5)
        self.assertLess(abs(box[3]-309),5)
        self.assertEqual(len(poly),4)

    def test_enclosed_white_label_not_bottom_end(self):
        image,points,old=self.sample()
        box,_,audit=refine_silhouette_caps(image,points,old,apply_candidates=True)
        self.assertTrue(audit['accepted'],audit)
        self.assertGreater(box[3],300)

    def test_horizontal_records_exact_fallback(self):
        image,_,old=self.sample()
        points=[[55,80],[110,80],[110,95],[55,95]]
        box,_,audit=refine_silhouette_caps(image,points,old)
        self.assertIs(box,old)
        self.assertEqual(audit['reason'],'not_upright_anchor')

    def test_default_keeps_existing_until_front_plane_review(self):
        image,points,old=self.sample()
        box,_,audit=refine_silhouette_caps(image,points,old)
        self.assertIs(box,old)
        self.assertFalse(audit['accepted'])
        self.assertTrue(audit['review_required'])
        self.assertIn('candidate_box',audit)
        self.assertEqual(audit['reason'],'printed_front_plane_requires_review')

    def test_blank_image_not_confident_object(self):
        image,points,old=self.sample();image[:]=210
        box,_,audit=refine_silhouette_caps(image,points,old,apply_candidates=True)
        self.assertFalse(audit['accepted'],audit)
        self.assertIs(box,old)

    def test_thin_neighbour_cannot_expand_the_side_corridor(self):
        image=np.full((300,160,3),200,np.uint8)
        image[40:260,45:78]=(30,80,145)
        image[30:270,79:112]=(30,80,145)
        old=[45,0,78,290];points=[[54,80],[68,80],[68,205],[54,205]]
        box,_,audit=refine_silhouette_caps(image,points,old,apply_candidates=True)
        if audit['accepted']:
            self.assertEqual(box[0],45)
            self.assertEqual(box[2],78)
        else:self.assertIs(box,old)

    def test_full_horizontal_d_evidence_unchanged(self):
        root=Path(__file__).resolve().parent
        path=root/'output/ocr-link-server/z2-scan-d-20261013-01/pipeline/input_hybrid.json'
        if not path.is_file():self.skipTest('saved D OCR unavailable')
        records=json.loads(path.read_text(encoding='utf8'))
        image=cv2.imread(str(root/'captures/new_flat_20261008/shelf_flat_d.jpg'))
        result=refine_silhouette_records(image,records,apply_candidates=True)
        for original,refined in zip(records,result):
            self.assertEqual(refined['book_box'],original['book_box'])
            self.assertEqual(refined['spine_polygon'],original['spine_polygon'])
            self.assertEqual(refined['text'],original['text'])


if __name__=='__main__':unittest.main()
