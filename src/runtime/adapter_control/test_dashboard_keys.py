import threading,unittest
from queue import Queue
from adapter_control.dashboard_runtime import LCDDashboard
class ScannerTests(unittest.TestCase):
 def test_edges_queued_without_display_loop(self):
  runtime=LCDDashboard.__new__(LCDDashboard);runtime.stop=threading.Event();runtime.status={}
  masks=iter([0,4,4,0,2,0,4,0])
  class Bridge:
   def buttons(self):return next(masks)
  class Finished:
   count=0
   def is_set(self):return self.count>=8
   def wait(self,seconds):self.count+=1
  runtime.bridge=Bridge();keys=Queue(maxsize=64)
  runtime.scan_buttons(keys,Finished())
  self.assertEqual([keys.get_nowait() for _ in range(keys.qsize())],['ok','down','ok'])
  self.assertEqual(runtime.status['keys_read'],3)
if __name__=='__main__':unittest.main()
