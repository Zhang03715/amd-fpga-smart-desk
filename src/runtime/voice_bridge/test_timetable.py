import unittest,json,tempfile
from pathlib import Path
from datetime import datetime
from voice_bridge.desk_features import FeatureService
from voice_bridge.pynq_service import encode
class TimetableTests(unittest.TestCase):
 def test_weekly_pages_and_edit_persistence(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';s=FeatureService(db_path=p,now=lambda:datetime(2026,11,6));data=json.loads(Path('config/timetable-2026-fall.json').read_text(encoding='utf-8'))
   self.assertEqual(s.execute('timetable.set',data)['total'],13)
   page=s.execute('timetable.get',{});self.assertEqual(page['total'],4);self.assertEqual(len(page['courses']),3);self.assertTrue(page['repeat_weekly'])
   nextpage=s.execute('timetable.get',{'weekday':5,'offset':3});self.assertEqual(nextpage['courses'][0]['name'],'数字图像处理')
   for weekday in range(1,8):self.assertLess(len(encode({'v':1,'type':'result','status':'success','data':s.execute('timetable.get',{'weekday':weekday})})),2048)
   s.execute('timetable.update',{'id':'d2-p1','name':'FPGA设计课程','location':'综101'});s.close();s=FeatureService(db_path=p)
   self.assertEqual(s.execute('timetable.get',{'weekday':2})['courses'][0]['name'],'FPGA设计课程');s.close()
if __name__=='__main__':unittest.main()
