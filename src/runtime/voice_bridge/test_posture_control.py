import json,tempfile,unittest
from pathlib import Path
from .posture_control import PostureControl
from .pynq_service import DeskService

class PostureControlTests(unittest.TestCase):
 def test_shelf_completion_and_failure_restore_posture_unless_paused(self):
  from concurrent.futures import Future
  class Control:
   def __init__(self):self.starts=0;self.prepared=0
   def start(self):self.starts+=1;return {'queued':True}
   def prepare_shelf(self):self.prepared+=1
   def switch(self,mode):return {'mode':mode}
  c=Control();s=DeskService(posture_control=c)
  try:
   self.assertEqual(s.run_shelf_job(lambda:'done'),'done');self.assertEqual(c.prepared,1)
   for failed in (False,True):
    future=Future()
    if failed:future.set_exception(ValueError('camera_failed'))
    else:future.set_result({'completed':True})
    s.jobs={'job':{'future':future,'kind':'calibration'}};s.posture_resume_pending=True
    s.collect_jobs()
   self.assertEqual(c.starts,2)
   s.execute('posture.config',{'operation':'camera','mode':'off'})
   s.jobs={};s.posture_resume_pending=True;s.collect_jobs()
   self.assertEqual(c.starts,2)
  finally:s.close()
 def test_saved_baseline_is_read_without_recalibration(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root);(p/'baseline.json').write_text('{}');(p/'status.json').write_text(json.dumps({'state':'normal','inference_ms':1000}))
   c=PostureControl(p);s=DeskService(posture_control=c)
   try:
    status=s.execute('posture.status',{})['detector'];self.assertTrue(status['baseline_saved']);self.assertEqual(status['state'],'normal');self.assertFalse((p/'calibration-request.json').exists())
    result=s.execute('posture.calibrate',{});self.assertTrue(result['queued']);self.assertFalse(result['completed']);self.assertTrue((p/'baseline.json').exists())
    with self.assertRaisesRegex(ValueError,'pending'):s.execute('posture.calibrate',{})
   finally:s.close()
 def test_offline_cannot_queue_calibration(self):
  with tempfile.TemporaryDirectory() as root:
   c=PostureControl(root)
   self.assertFalse(c.status()['available'])
   with self.assertRaisesRegex(ValueError,'not_running'):c.calibrate()

if __name__=='__main__':unittest.main()
