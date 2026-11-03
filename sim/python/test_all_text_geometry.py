import json
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from hybrid_book_locator import locate


class AllTextGeometryTests(unittest.TestCase):
    def test_all_text_mode_keeps_chinese_when_english_scores_higher(self):
        workspace_output=Path(__file__).resolve().parent/'output'
        with tempfile.TemporaryDirectory(dir=workspace_output) as tmp:
            root=Path(tmp);image=root/'shelf.jpg'
            assert root.resolve().is_relative_to(workspace_output.resolve())
            pixels=np.full((360,600,3),180,np.uint8)
            pixels[40:150]=(70,140,160);pixels[180:300]=(130,90,180)
            cv2.imwrite(str(image),pixels)
            rows=[[[[60,65],[260,65],[260,105],[60,105]],'高等数学',.99],
                  [[[80,200],[400,200],[400,240],[80,240]],'PEKING UNIVERSITY PRESS',.98]]
            locate(image,'BLIND_EVALUATION',root/'all',1.,supplied_ocr=rows,draw_labels=False,all_texts=True)
            result=json.loads((root/'all/shelf_hybrid.json').read_text(encoding='utf8'))
            self.assertEqual([r['text'] for r in result],['高等数学','PEKING UNIVERSITY PRESS'])
            self.assertTrue(all(r['match_score']==0. for r in result))
            locate(image,'BLIND_EVALUATION',root/'default',0.,supplied_ocr=rows,draw_labels=False)
            result=json.loads((root/'default/shelf_hybrid.json').read_text(encoding='utf8'))
            self.assertEqual([r['text'] for r in result],['PEKING UNIVERSITY PRESS'])


if __name__=='__main__':
    unittest.main()
