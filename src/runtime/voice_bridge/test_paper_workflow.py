import unittest,tempfile
from pathlib import Path
from voice_bridge.paper_workflow import PaperWorkflow
class Motors:
 def __init__(self):self.calls=[];self.s=dict(available=True,state='disabled',completed_cycles=0,reference_valid=False)
 def status(self):return dict(self.s)
 def home(self,confirmed):
  if confirmed is not True:raise ValueError('manual_reference_confirmation_required')
  self.calls.append('home');self.s.update(state='ready',reference_valid=True);return {}
 def feed(self):
  if not self.s['reference_valid'] or self.s['state']!='ready':raise ValueError('not_ready')
  self.calls.append('feed');self.s['state']='waiting_classification';return {}
 def dispatch(self,slot):
  if self.s['state']!='waiting_classification':raise ValueError('not_waiting')
  self.calls.append(('dispatch',slot));self.s['state']='ejecting'
 def stop(self):self.calls.append('stop');self.s.update(state='fault',reference_valid=False);return {}
 def release(self):return self.stop()
 def close(self):pass
class WorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.motor=Motors();self.review=False;self.restore_count=0
  def classify(image,sheet,source):return dict(sheet_id=sheet,label_id='physics',label_name='物理',slot=None if self.review else 2,needs_review=self.review,profile_sha256='a'*64,reason='实验报告')
  def restore():self.restore_count+=1
  self.flow=PaperWorkflow(self.motor,lambda sheet:(b'jpeg',{},'http://test/paper.jpg'),classify,Path(self.tmp.name)/'db',restore)
 def tearDown(self):self.flow.close();self.tmp.cleanup()
 def start(self):self.flow.home({'manual_reference_confirmed':True});self.flow.feed({})
 def test_classification_never_auto_dispatches(self):
  self.start();sheet=self.flow.classify();self.assertEqual(self.motor.calls,['home','feed']);self.assertEqual(sheet['state'],'review');self.assertEqual(self.restore_count,1)
  params=dict(sheet_id=sheet['sheet_id'],confirmed=True,slot=2,profile_sha256='a'*64)
  self.flow.dispatch(params);self.assertEqual(self.motor.calls[-1],('dispatch',2))
  with self.assertRaises(ValueError):self.flow.dispatch(params)
  self.motor.s.update(state='ready',completed_cycles=1)
  self.assertEqual(self.flow.status()['sheet']['state'],'motion_complete');self.assertFalse(self.flow.status()['physical_delivery_verified'])
 def test_uncertain_requires_manual_selection(self):
  self.start();self.review=True;sheet=self.flow.classify()
  params=dict(sheet_id=sheet['sheet_id'],confirmed=True,slot=3,profile_sha256='a'*64)
  with self.assertRaisesRegex(ValueError,'manual_label'):self.flow.dispatch(params)
  params['manual_override']=True;self.flow.dispatch(params)
 def test_home_and_dispatch_guards(self):
  with self.assertRaises(ValueError):self.flow.home({})
  self.start();sheet=self.flow.classify()
  for params in [dict(sheet_id='wrong',confirmed=True),dict(sheet_id=sheet['sheet_id'],confirmed=False),dict(sheet_id=sheet['sheet_id'],confirmed=True,slot=4),dict(sheet_id=sheet['sheet_id'],confirmed=True,slot=2,profile_sha256='b'*64)]:
   with self.assertRaises(ValueError):self.flow.dispatch(params)
  self.assertEqual(self.motor.calls,['home','feed'])
 def test_fault_does_not_become_delivery_success(self):
  self.start();sheet=self.flow.classify();self.flow.dispatch(dict(sheet_id=sheet['sheet_id'],confirmed=True,slot=2,profile_sha256='a'*64));self.flow.stop()
  self.assertEqual(self.flow.status()['sheet']['state'],'interrupted')
 def test_reopen_never_resumes_motion(self):
  self.start();self.flow.classify();self.flow.close()
  self.flow=PaperWorkflow(self.motor,None,None,Path(self.tmp.name)/'db');self.assertIsNone(self.flow.status()['sheet']);self.assertEqual(self.motor.calls,['home','feed'])
 def test_cancel_during_classification_remains_interrupted(self):
  self.start()
  def classify(*args):
   self.flow.stop();return dict(sheet_id=self.flow.current['sheet_id'],slot=2,needs_review=False,profile_sha256='a'*64)
  self.flow.classify_remote=classify
  with self.assertRaisesRegex(ValueError,'cancelled'):self.flow.classify()
  self.assertEqual(self.flow.status()['sheet']['state'],'interrupted')
  self.assertEqual(self.restore_count,1)
 def test_stale_result_rejected_without_motion(self):
  self.start();self.flow.classify_remote=lambda *args:dict(sheet_id='old-sheet')
  with self.assertRaisesRegex(ValueError,'identity'):self.flow.classify()
  self.assertEqual(self.flow.status()['sheet']['state'],'classification_failed')
  self.assertEqual(self.motor.calls,['home','feed'])
 def test_isolated_platform_requires_confirmation_and_no_sheet(self):
  self.flow.home({'manual_reference_confirmed':True})
  self.motor.platform_test=lambda:self.motor.calls.append('M4-only') or {'test_only':True}
  with self.assertRaisesRegex(ValueError,'confirmation'):self.flow.dispatch({'test_only':True})
  self.flow.dispatch({'test_only':True,'confirmed':True})
  self.assertEqual(self.motor.calls,['home','M4-only'])
  self.assertIsNone(self.flow.current)
  self.flow.feed({})
  with self.assertRaisesRegex(ValueError,'unfinished'):self.flow.dispatch({'test_only':True,'confirmed':True})
 def test_wrong_capture_never_moves_motors_or_changes_sheet(self):
  def extract(image,sheet,source,operation):
   self.assertEqual(operation,'wrong_question');return {'saved_count':1,'desktop_folder':'test-desktop'}
  self.flow.classify_remote=extract
  result=self.flow.capture_wrong_question()
  self.assertEqual(result['saved_count'],1);self.assertEqual(self.motor.calls,[]);self.assertIsNone(self.flow.current);self.assertEqual(self.restore_count,1)
 def test_wrong_capture_rejected_during_paper_process(self):
  self.start()
  with self.assertRaises(ValueError):self.flow.capture_wrong_question()
 def test_full_cycle_dispatches_only_certain_result(self):
  self.flow.home({'manual_reference_confirmed':True})
  original=self.motor.dispatch
  def dispatch(slot):
   original(slot);self.motor.s.update(state='ready',completed_cycles=1)
  self.motor.dispatch=dispatch
  result=self.flow.run_full_cycle()
  self.assertEqual(result['state'],'motion_complete');self.assertIn(('dispatch',2),self.motor.calls);self.assertFalse(self.flow.auto_running)
 def test_full_cycle_stops_for_review(self):
  self.flow.home({'manual_reference_confirmed':True});self.review=True
  result=self.flow.run_full_cycle()
  self.assertTrue(result['manual_review_required']);self.assertEqual(self.motor.calls,['home','feed'])
 def test_batch_completes_each_sheet_before_next_feed(self):
  self.flow.home({'manual_reference_confirmed':True})
  def dispatch(slot):
   self.motor.calls.append(('dispatch',slot));self.motor.s.update(state='ready',completed_cycles=self.motor.s['completed_cycles']+1)
  self.motor.dispatch=dispatch
  result=self.flow.run_full_cycle(3)
  self.assertEqual(result['batch_completed'],3)
  self.assertEqual(self.motor.calls,['home','feed',('dispatch',2),'feed',('dispatch',2),'feed',('dispatch',2)])
 def test_batch_review_prevents_next_feed(self):
  self.flow.home({'manual_reference_confirmed':True});self.review=True
  self.flow.run_full_cycle(3)
  self.assertEqual(self.motor.calls,['home','feed']);self.assertEqual(self.flow.batch_completed,0)
 def test_invalid_batch_count_never_moves(self):
  for count in (0,101,True,1.5,'3'):
   with self.assertRaisesRegex(ValueError,'invalid_paper_count'):self.flow.run_full_cycle(count)
  self.assertEqual(self.motor.calls,[])
if __name__=='__main__':unittest.main()
