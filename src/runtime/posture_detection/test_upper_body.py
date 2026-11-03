import copy
import unittest
from posture_detection.upper_body import assess, features, calibrate


def points():
    p = [[0, 0, 0] for _ in range(17)]
    p[0], p[5], p[6] = [160, 70, .95], [100, 130, .95], [220, 130, .95]
    return p


class UpperBodyTests(unittest.TestCase):
    def test_hidden_hips_allowed_but_calibration_required(self):
        self.assertEqual(assess(points(), (320,240))['status'], 'calibration_needed')

    def test_reference_and_deviation(self):
        p = points()
        base = calibrate([features(p, (320,240)) for _ in range(15)], 'camera0')
        self.assertEqual(assess(p, (320,240), base)['status'], 'within_reference')
        changed = copy.deepcopy(p); changed[0][0] += 30
        self.assertEqual(assess(changed, (320,240), base)['status'], 'deviation')
        changed = copy.deepcopy(p); changed[6][1] += 30
        self.assertIn('shoulder_angle', assess(changed, (320,240), base)['reasons'])
        self.assertEqual(assess(p, (320,240), base, camera_id='other')['reason'], 'invalid_calibration')

    def test_bad_evidence(self):
        for i, value in [(0, [160,70,.1]), (5, [-1,130,.9]), (6, [float('nan'),130,.9])]:
            p = points();p[i] = value
            self.assertEqual(assess(p,(320,240))['status'], 'unknown')
        self.assertEqual(assess(points(),(320,240),age_seconds=3)['reason'], 'stale_frame')

    def test_calibration_quality(self):
        with self.assertRaises(ValueError):calibrate([], 'camera0')
        samples = [features(points(), (320,240)) for _ in range(15)]
        samples[-1] = dict(samples[-1],head_offset=1)
        with self.assertRaises(ValueError):calibrate(samples, 'camera0')


if __name__ == '__main__':unittest.main()
