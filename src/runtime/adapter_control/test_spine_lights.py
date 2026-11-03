import unittest
from .spine_lights import SpineLightMapper


class MappingTests(unittest.TestCase):
    def mapper(self,reverse=False):
        positions=list(range(10,151,10))
        return SpineLightMapper(calibration_id='measured',camera_id='2',image_size=[200,100],
                               axis='x',positions=positions[::-1] if reverse else positions,
                               shelf_range=[0,160])
    def plan(self,m,span,target='book'):
        return m.plan([span[0],10,span[1],90],camera_id='2',image_size=[200,100],target_id=target)
    def test_center_between_wide_and_reverse(self):
        m=self.mapper()
        self.assertEqual(self.plan(m,(9,11)),[0])
        self.assertEqual(self.plan(m,(14,16),'b'),[0,1])
        self.assertEqual(self.plan(m,(25,65),'c'),[2,3,4,5])
        self.assertEqual(self.plan(self.mapper(True),(14,16)),[13,14])
    def test_hysteresis_is_target_specific_and_does_not_accumulate_drift(self):
        m=self.mapper();self.assertEqual(self.plan(m,(9,11)),[0])
        self.assertEqual(self.plan(m,(10.5,12.5)),[0])
        self.assertEqual(self.plan(m,(12,14)),[0,1])
        self.assertEqual(self.plan(m,(9,11),'new'),[0])
    def test_inactive_tail_and_bad_geometry(self):
        m=self.mapper();p=m.pixels([0,14])
        self.assertEqual(len(p),30);self.assertTrue(all(x==(0,0,0) for x in p[15:]))
        with self.assertRaises(ValueError):m.pixels([15])
        with self.assertRaises(ValueError):self.plan(m,(170,180))
        with self.assertRaises(ValueError):m.plan([1,1,2,2],camera_id='0',image_size=[200,100],target_id='a')
