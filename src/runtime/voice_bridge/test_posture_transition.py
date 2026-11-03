import unittest
from .desk_features import FeatureService
class Transitions(unittest.TestCase):
 def test_edges(self):
  clock=[0];f=FeatureService(clock=lambda:clock[0]);f.transition_reminders=True
  def sample(state,dt=1):
   clock[0]+=dt;return f.execute('posture.update',{'classification':state})['reminded']
  try:
   self.assertFalse(sample('bad'))
   self.assertFalse(sample('good'))
   self.assertTrue(sample('bad'))
   self.assertFalse(sample('bad',70))
   self.assertFalse(sample('unknown'))
   self.assertFalse(sample('bad'))
   self.assertFalse(sample('good'))
   self.assertTrue(sample('bad'))
   sample('good');self.assertFalse(sample('bad',10))
  finally:f.close()
if __name__=='__main__':unittest.main()
