import unittest
from .focus_lights import plan
class Countdown(unittest.TestCase):
 def test_count_and_mask(self):
  p,n=plan({'state':'running','phase':'focus','total_seconds':1500,'remaining_seconds':1500});self.assertEqual(n,14);self.assertTrue(all(p[i]==(0,0,0) for i in list(range(30))+list(range(44,60))))
  self.assertEqual(plan({'state':'paused','total_seconds':1500,'remaining_seconds':750})[1],7)
  self.assertEqual(plan({'state':'running','total_seconds':1500,'remaining_seconds':1})[1],1)
  self.assertEqual(plan({'state':'idle','remaining_seconds':100})[1],0)
 def test_phase_color(self):
  t={'state':'running','total_seconds':300,'remaining_seconds':300,'phase':'rest'};p,n=plan(t);self.assertEqual(p[30],(0,255,80))
if __name__=='__main__':unittest.main()
