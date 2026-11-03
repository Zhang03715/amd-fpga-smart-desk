import unittest
from PIL import Image,ImageDraw
from .grouping import group_questions
from .red_marks import detect_red_crosses,associate_marks
class Tests(unittest.TestCase):
 def test_columns_and_subquestions(self):
  def row(t,x,y):return {'text':t,'score':.99,'box':[[x,y],[x+100,y],[x+100,y+20],[x,y+20]]}
  r=group_questions([row('1. test',100,100),row('(1) subquestion',100,200),row('2. test',100,500),row('3. test',900,100)],(1654,2339))
  self.assertEqual(len(r['questions']),3);self.assertEqual(r['questions'][0]['box'][2],858);self.assertTrue(all(q['review_required'] for q in r['questions']))
 def test_cross_not_underline_or_tick(self):
  im=Image.new('RGB',(500,200),'white');d=ImageDraw.Draw(im);d.line((30,30,70,70),fill='red',width=6);d.line((30,70,70,30),fill='red',width=6);d.line((120,50,180,50),fill='red',width=6);d.line([(240,50),(260,70),(300,20)],fill='red',width=6)
  marks=detect_red_crosses(im);self.assertEqual(len(marks),1)
  result=associate_marks([{'box':[0,0,100,100]}],marks);self.assertTrue(result['questions'][0]['marked']);self.assertTrue(result['review_required'])
 def test_no_anchor_is_not_success(self):self.assertEqual(group_questions([], (500,500))['questions'],[])
 def test_desktop_export_only_marked_and_no_overwrite(self):
  import tempfile,json
  from pathlib import Path
  from .export_desktop import export_marked
  with tempfile.TemporaryDirectory() as f:
   root=Path(f);source=root/'source';source.mkdir();Image.new('RGB',(50,50),'white').save(source/'q.png')
   result={'questions':[{'number':2,'marked':True,'crop':'q.png'},{'number':3,'marked':False,'crop':'q.png'}]}
   first=Path(export_marked(result,source,root/'Desktop'));second=Path(export_marked(result,source,root/'Desktop'))
   self.assertNotEqual(first,second);self.assertEqual(len(list(first.glob('*.png'))),1);self.assertTrue((first/'识别说明.json').exists())
   with self.assertRaises(ValueError):export_marked({'questions':[{'number':1,'marked':True,'crop':'../outside.png'}]},source,root/'Desktop')
if __name__=='__main__':unittest.main()
