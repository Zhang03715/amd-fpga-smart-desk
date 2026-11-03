import unittest
from board_ocr.optimization_20261013.query_rescue import one_edit,candidates,confirmed
class QueryTests(unittest.TestCase):
 def test_edit_is_only_candidate_gate(self):
  self.assertTrue(one_edit('中国近规代史纲要','中国近现代史纲要'));self.assertTrue(one_edit('国近现代史纲要','中国近现代史纲要'));self.assertFalse(one_edit('马原','马克思主义基本原理'));self.assertFalse(one_edit('中国古代历史纲要','中国近现代史纲要'))
 def test_two_models_must_actually_read_exact_target(self):
  target='马克思主义基本原理'
  rows=[dict(model='primary',text='马克恩主义基本原理',confidence=.999),dict(model='secondary',text='马克恩主义基本原理',confidence=.999)]
  self.assertFalse(confirmed(rows,target))
  rows[0]['text']=target;self.assertFalse(confirmed(rows,target));rows[1]['text']=target;self.assertTrue(confirmed(rows,target))
 def test_short_titles_no_fuzzy_candidates(self):
  self.assertEqual(candidates([dict(v4_text='解析几伺',v4_confidence=.99,points=[[0,0],[10,0],[10,100],[0,100]])],'解析几何'),[])
if __name__=='__main__':unittest.main()
