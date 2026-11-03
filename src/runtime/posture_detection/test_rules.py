import copy
import json
import math
import unittest
from posture_detection.rules import calibrate, classify, extract_features


def landmarks():
    points = [dict(x=.5, y=.5, z=0, visibility=.95, presence=.95) for _ in range(33)]
    for index, x, y in [(0,.5,.25),(7,.47,.25),(8,.53,.25),
                        (11,.35,.4),(12,.65,.4),(23,.4,.75),(24,.6,.75)]:
        points[index].update(x=x, y=y)
    return points


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.points = landmarks()
        self.baseline = self.base('front')

    def base(self, view):
        return calibrate([extract_features(self.points, (640,480), view) for _ in range(15)], view)

    def test_calibrated_good_json_roundtrip(self):
        baseline = json.loads(json.dumps(self.baseline))
        result = classify(self.points, (640,480), baseline)
        self.assertEqual(result['classification'], 'good')
        self.assertEqual(result['confidence'], .95)

    def test_head_drop(self):
        self.points[0]['y'] += .12
        self.assertEqual(classify(self.points, (640,480), self.baseline)['classification'], 'bad')

    def test_shoulder_tilt(self):
        self.points[12]['y'] += .1
        result = classify(self.points, (640,480), self.baseline)
        self.assertIn('lateral_shoulder_tilt', result['reasons'])

    def test_side_relative_projection(self):
        baseline = self.base('side')
        self.points[7]['x'] += .1
        result = classify(self.points, (640,480), baseline, view='side')
        self.assertEqual(result['classification'], 'bad')
        self.assertIn('ear_shoulder_offset_changed_2d', result['reasons'])

    def test_unknown_no_calibration_person_occlusion_stale(self):
        self.assertEqual(classify(self.points, (640,480))['classification'], 'unknown')
        self.assertEqual(classify([], (640,480), self.baseline)['classification'], 'unknown')
        self.assertEqual(classify(self.points, (640,480), self.baseline, age_seconds=3)['classification'], 'unknown')
        self.points[11]['visibility'] = .3
        self.assertEqual(classify(self.points, (640,480), self.baseline)['classification'], 'unknown')

    def test_invalid_point(self):
        for value in (math.nan, math.inf, 1.2):
            points = copy.deepcopy(self.points)
            points[0]['x'] = value
            self.assertEqual(classify(points, (640,480), self.baseline)['classification'], 'unknown')

    def test_camera_and_scale_guard(self):
        self.assertEqual(classify(self.points, (640,480), self.baseline, camera_id='other')['classification'], 'unknown')
        self.assertEqual(classify(self.points, (480,640), self.baseline)['classification'], 'unknown')
        self.points[11]['x'] = .1
        self.points[12]['x'] = .9
        self.assertEqual(classify(self.points, (640,480), self.baseline)['classification'], 'unknown')

    def test_threshold_can_be_configured(self):
        self.points[0]['y'] += .09
        self.assertEqual(classify(self.points, (640,480), self.baseline)['classification'], 'bad')
        self.assertEqual(classify(self.points, (640,480), self.baseline, config={'front_head_drop_delta':.5})['classification'], 'good')

    def test_calibration_requires_valid_stable_samples(self):
        with self.assertRaises(ValueError):
            calibrate([extract_features(self.points, (640,480))])
        samples = [extract_features(self.points, (640,480)) for _ in range(15)]
        samples[0]['metrics']['center_y'] = .9
        with self.assertRaises(ValueError):
            calibrate(samples)

    def test_bad_config_rejected(self):
        with self.assertRaises(ValueError):
            classify(self.points, (640,480), self.baseline, config={'max_age':-1})


if __name__ == '__main__':
    unittest.main()
