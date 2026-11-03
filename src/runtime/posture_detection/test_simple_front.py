import copy
import unittest
from .desk_rules import features,calibrate
from .simple_front import assess
from .test_desk_rules import points


class SimpleFrontTests(unittest.TestCase):
    def setUp(self):
        self.p=points()
        self.base=calibrate([features(self.p,(640,480),'front') for _ in range(15)],'front','test')
    def test_normal_head_down_shoulder_tilt_and_both(self):
        def state(p):return assess(p,(640,480),self.base,'test')['state']
        self.assertEqual(state(self.p),'normal')
        q=copy.deepcopy(self.p);q[0]['y']=.36
        self.assertEqual(state(q),'head_down')
        q=copy.deepcopy(self.p);q[11]['y']=.3;q[12]['y']=.5
        self.assertEqual(state(q),'shoulder_tilt')
        q[0]['y']=.5
        self.assertEqual(state(q),'head_down_and_shoulder_tilt')
    def test_head_translation_is_not_shoulder_tilt(self):
        self.p[0]['x']+=.15
        self.assertEqual(assess(self.p,(640,480),self.base,'test')['state'],'normal')
    def test_unknown_is_not_normal(self):
        self.p[11]['visibility']=.1
        r=assess(self.p,(640,480),self.base,'test')
        self.assertEqual(r['state'],'unknown');self.assertIsNone(r['head_down'])
        self.assertFalse(r['reminder_candidate'])
