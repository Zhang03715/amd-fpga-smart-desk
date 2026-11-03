import threading,unittest
from adapter_control.paper_motors import PaperMotors
class Bridge:
 def __init__(self):self.lock=threading.RLock();self.page=0;self.commands=[]
 def command(self,op,value=0):
  self.commands.append((op,value))
  if op==0x45:self.page=value
 def status(self):
  pages={1:3|64|128,2:7,3:0,4:0,5:0,6:267,7:1<<8}
  return 0x5a323000|(pages.get(self.page,0)<<2)
class MotorTests(unittest.TestCase):
 def test_status_decode_and_software_only_guard(self):
  b=Bridge();m=PaperMotors(b)
  try:
   s=m.status();self.assertEqual(s['state'],'waiting_classification');self.assertEqual(s['completed_cycles'],7);self.assertEqual(s['slot'],2);self.assertEqual(s['platform_pulses'],267);self.assertFalse(s['motion_enabled']);self.assertEqual(b.page,0)
   with self.assertRaisesRegex(ValueError,'not_enabled'):m.dispatch(2)
   self.assertFalse(any(op==0x42 for op,_ in b.commands))
  finally:m.close()
 def test_legacy_overlay_rejected(self):
  b=Bridge();b.status=lambda:0x5a321000;m=PaperMotors(b)
  self.assertFalse(m.status()['available'])
  with self.assertRaisesRegex(ValueError,'overlay'):m.home(True)
  m.close()
if __name__=='__main__':unittest.main()
