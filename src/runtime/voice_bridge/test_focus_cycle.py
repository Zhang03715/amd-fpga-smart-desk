import unittest
from voice_bridge.pynq_service import DeskService

class FocusCycleTests(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.service=DeskService(clock=lambda:self.now)
    def tearDown(self): self.service.close()
    def test_repeat_pause_stop(self):
        s=self.service;s.execute('timer.start',{})
        self.now=1500;s.poll_events()
        self.assertEqual((s.timer_status()['phase'],s.timer_status()['remaining_seconds']),('rest',300))
        self.now=1800;s.poll_events()
        self.assertEqual((s.timer_status()['phase'],s.timer_status()['cycle']),('focus',2))
        self.now=1810;s.execute('timer.pause',{})
        self.now=9000;s.poll_events();self.assertEqual(s.timer_status()['remaining_seconds'],1490)
        s.execute('timer.resume',{});self.assertEqual(s.timer_status()['remaining_seconds'],1490)
        s.execute('timer.stop',{});self.now=20000;s.poll_events();self.assertEqual(s.timer_status()['state'],'idle')
    def test_led_count_and_priority(self):
        class Adapter:
            def __init__(self):self.pixels=[]
            def posture_alert(self,active):pass
            def focus_countdown(self,pixels):self.pixels=pixels
        s=self.service;a=Adapter();s.book_adapter=a;s.execute('timer.start',{})
        s.poll_events();self.assertEqual(sum(any(p) for p in a.pixels),14)
        self.now=750;s.poll_events();self.assertEqual(sum(any(p) for p in a.pixels),7)
        self.now=1500;s.poll_events();s.poll_events()
        self.assertEqual(a.pixels[30],(0,255,80))
        s.execute('timer.stop',{});s.poll_events();self.assertFalse(any(any(p) for p in a.pixels))

if __name__=='__main__':unittest.main()
