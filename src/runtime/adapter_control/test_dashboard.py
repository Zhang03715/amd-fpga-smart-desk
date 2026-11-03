import unittest
from PIL import Image
from .dashboard import Dashboard,find_font
from .lcd import ST7789,Panel

class DashboardTests(unittest.TestCase):
 def snapshot(self,state='normal'):
  return {'pose':{'detector':{'available':True,'state':state,'baseline_saved':True,'camera_mode':'posture'},'red_light_active':state=='head_down'},'s3':True,'health':{'ocr':'ready'},'calibrated':True}
 def test_navigation_requires_two_confirmations_to_replace_reference(self):
  ui=Dashboard(find_font());snap=self.snapshot();ui.key('ok',snap);ui.key('down',snap);ui.key('ok',snap)
  self.assertEqual(ui.page,'posture');self.assertIsNone(ui.key('ok',snap))
  self.assertEqual(ui.key('ok',snap),('posture.calibrate',{}))
  ui.key('back',snap);self.assertEqual(ui.page,'menu');ui.key('back',snap);self.assertEqual(ui.page,'home')
 def test_unknown_and_stale_do_not_render_as_normal(self):
  ui=Dashboard(find_font());ui.page='posture'
  normal=ui.render(self.snapshot());bad=ui.render(self.snapshot('head_down'))
  stale=self.snapshot();stale['stale']=True
  self.assertNotEqual(normal.tobytes(),bad.tobytes())
  self.assertNotEqual(normal.tobytes(),ui.render(stale).tobytes())
 def test_all_pages_render_and_preview_does_not_open_camera(self):
  ui=Dashboard(find_font())
  for page in ('home','menu','study','settings','posture','book','focus','exam','files','wrongs','faults','preview'):
   ui.page=page;self.assertEqual(ui.render(self.snapshot()).size,(240,320))
  self.assertEqual(ui.render(self.snapshot(),Image.new('RGB',(800,480),'blue')).size,(240,320))
 def test_dirty_bands_avoid_transmitting_unchanged_middle(self):
  class Bridge:
   def command(self,*args):pass
   def data_bytes(self,*args):pass
  frame=Image.new('RGB',(32,64),'black');lcd=ST7789(Bridge(),Panel(width=32,height=64),dirty_band_height=8)
  self.assertEqual(lcd.show(frame),4096)
  changed=frame.copy();changed.putpixel((1,1),(255,0,0));changed.putpixel((30,62),(0,255,0))
  self.assertEqual(lcd.show(changed),4)
  self.assertEqual(lcd.show(changed),0)

if __name__=='__main__':unittest.main()

class StudyPagesTests(unittest.TestCase):
 def test_focus_controls_and_live_snapshot(self):
  from .dashboard_runtime import lcd_snapshot
  from voice_bridge.pynq_service import DeskService
  service=DeskService(simulate=True)
  try:
   service.execute('exam.set',{'name':'期末','date':'2026-12-31'})
   service.execute('paper.record.create',{'title':'数学讲义'})
   data=lcd_snapshot(service,True)
   self.assertTrue(data['exam']['configured']);self.assertEqual(data['records'][0]['title'],'数学讲义')
   ui=Dashboard(find_font());ui.page='focus'
   self.assertEqual(ui.key('ok',{'timer':{'state':'idle'}}),('timer.start',{'minutes':25}))
   self.assertEqual(ui.key('ok',{'timer':{'state':'running'}}),('timer.pause',{}))
   self.assertEqual(ui.key('ok',{'timer':{'state':'paused'}}),('timer.resume',{}))
   for page in ['focus','exam','files','faults']:
    ui.page=page;self.assertEqual(ui.render(data).size,(240,320))
  finally:service.close()
