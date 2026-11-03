import unittest
from .led2_layout import Led2Layout
from .spine_lights import SpineLightMapper


class LayoutTests(unittest.TestCase):
    def test_physical_numbering_and_unused_pixels(self):
        p=Led2Layout.pixels(horizontal=[0,13],vertical=[0,8])
        self.assertEqual(len(p),60)
        self.assertEqual(p[30],(0,255,0));self.assertEqual(p[43],(0,255,0))
        self.assertEqual(p[29],(0,0,255));self.assertEqual(p[21],(0,0,255))
        self.assertTrue(all(x==(0,0,0) for x in p[:21]))
        self.assertTrue(all(x==(0,0,0) for x in p[44:]))
        self.assertEqual(Led2Layout.info()['inactive_indices'],list(range(21))+list(range(44,60)))
        with self.assertRaises(ValueError):Led2Layout.pixels(horizontal=[14])
        with self.assertRaises(ValueError):Led2Layout.pixels(vertical=[9])
    def test_measured_mapper_returns_real_chain_indices(self):
        m=SpineLightMapper(calibration_id='x',camera_id='2',image_size=[200,100],axis='x',
                          positions=list(range(10,141,10)),shelf_range=[0,150],
                          physical_count=60,active_count=14,pixel_indices=Led2Layout.horizontal)
        indices=m.plan([14,10,16,90],camera_id='2',image_size=[200,100],target_id='book')
        self.assertEqual(indices,[30,31]);self.assertEqual(len(m.pixels(indices)),60)
        self.assertTrue(all(x==(0,0,0) for x in m.pixels(indices)[44:]))
        self.assertTrue(all(x==(0,0,0) for x in m.pixels(indices)[:30]))
