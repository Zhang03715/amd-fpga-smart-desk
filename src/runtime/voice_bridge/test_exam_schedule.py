import tempfile,unittest
from pathlib import Path
from voice_bridge.desk_features import FeatureService
class ScheduleTests(unittest.TestCase):
 def test_preserve_fields_other_exams_and_restart(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'data.sqlite';s=FeatureService(db_path=path)
   s.execute('exam.set',dict(name='数字图像处理',date='2026-11-06',start='15:35',end='17:15',location='综260'))
   s.execute('exam.set',dict(name='射频电子线路',date='2026-11-20'))
   s.execute('exam.set',dict(name='数字图像处理',location='综261'))
   rows=s.execute('exam.get',{})['exams'];self.assertEqual(len(rows),2);self.assertEqual(rows[0]['start'],'15:35');self.assertEqual(rows[0]['location'],'综261')
   with self.assertRaises(ValueError):s.execute('exam.set',dict(name='数字图像处理',end='08:00'))
   s.close();s=FeatureService(db_path=path);self.assertEqual(s.execute('exam.get',{})['total'],2)
   s.execute('exam.clear',{'name':'数字图像处理'});self.assertEqual(s.execute('exam.get',{})['name'],'射频电子线路');s.close()
if __name__=='__main__':unittest.main()
