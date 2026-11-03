import copy
import math
import unittest
from .desk_rules import assess,features,calibrate,SustainedCue


def points():
    p=[dict(x=.5,y=.5,z=0.,visibility=.99,presence=1.) for _ in range(33)]
    for i,x,y in [(0,.5,.2),(7,.47,.2),(8,.53,.2),(11,.3,.4),(12,.7,.4),(23,.4,.8),(24,.6,.8)]:p[i].update(x=x,y=y)
    return p


class DeskRulesTests(unittest.TestCase):
    def test_front_reading_deep_head_and_lateral(self):
        p=points();base=calibrate([features(p,(640,480),'front') for _ in range(15)],'front','test')
        self.assertEqual(assess(p,(640,480),base,'front','test')['state'],'within_reference')
        q=copy.deepcopy(p);q[0]['y']=.33
        result=assess(q,(640,480),base,'front','test')
        self.assertEqual(result['state'],'head_lowered');self.assertFalse(result['reminder_candidate'])
        q[0]['y']=.45
        self.assertEqual(assess(q,(640,480),base,'front','test')['state'],'deep_head_lowered')
        q=copy.deepcopy(p);q[0]['x']+=.15
        self.assertTrue(assess(q,(640,480),base,'front','test')['reminder_candidate'])

    def test_side_head_motion_alone_not_reminder(self):
        p=points();base=calibrate([features(p,(640,480),'side') for _ in range(15)],'side','test')
        p[7]['x']-=.2;p[8]['x']-=.2
        r=assess(p,(640,480),base,'side','test')
        self.assertEqual(r['state'],'reading_or_head_shift');self.assertFalse(r['reminder_candidate'])
        p[11]['x']-=.15;p[12]['x']-=.15
        self.assertEqual(assess(p,(640,480),base,'side','test')['state'],'trunk_lean')

    def test_bad_evidence_and_reference(self):
        p=points();base=calibrate([features(p,(640,480),'front') for _ in range(15)],'front','test')
        for i,value in [(0,float('nan')),(11,-.1)]:
            q=copy.deepcopy(p);q[i]['x']=value
            self.assertEqual(assess(q,(640,480),base,'front','test')['state'],'unknown')
        self.assertEqual(assess(p,(640,480),base,'front','other')['reasons'],['invalid_calibration'])
        self.assertEqual(assess(p,(640,480),base,'front','test',3)['reasons'],['stale_frame'])
        with self.assertRaises(ValueError):calibrate([],'front','test')

    def test_shoulder_frame_head_height_survives_rotation(self):
        p=points();original=features(p,(640,480),'front');q=copy.deepcopy(p)
        angle=math.radians(15)
        for i in [0,11,12]:
            x,y=p[i]['x']*640-320,p[i]['y']*480-192
            q[i]['x']=(320+x*math.cos(angle)-y*math.sin(angle))/640
            q[i]['y']=(192+x*math.sin(angle)+y*math.cos(angle))/480
        rotated=features(q,(640,480),'front')
        self.assertAlmostEqual(original['head_height'],rotated['head_height'])
        self.assertAlmostEqual(original['head_offset'],rotated['head_offset'])

    def test_invalid_image_size_and_confidence(self):
        for size in [(float('nan'),480),(640,float('inf')),(0,480)]:
            self.assertIsNone(features(points(),size,'front'))
        p=points();p[11]['visibility']=.2
        self.assertIsNone(features(p,(640,480),'front'))

    def test_persistence_gap_unknown_repeat_and_sessions(self):
        gate=SustainedCue(duration=1,max_gap=.6)
        cue=dict(state='lateral_deviation',reminder_candidate=True)
        self.assertFalse(gate.update(0,0,'a',cue));self.assertFalse(gate.update(.5,1,'a',cue))
        self.assertTrue(gate.update(1.,2,'a',cue))
        self.assertFalse(gate.update(1.1,2,'a',cue))
        self.assertFalse(gate.update(1.2,3,'a',cue))
        self.assertFalse(gate.update(3.,4,'a',cue))
        self.assertFalse(gate.update(3.5,5,'b',cue))
        self.assertFalse(gate.update(4.,6,'b',dict(state='unknown',reminder_candidate=False)))
