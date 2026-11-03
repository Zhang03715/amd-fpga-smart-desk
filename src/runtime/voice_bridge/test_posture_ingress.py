import json
import unittest
from urllib.request import Request, urlopen
from voice_bridge.pynq_service import DeskService
from voice_bridge.posture_ingress import PostureIngress


class DetectorIngressTests(unittest.TestCase):
    def setUp(self):
        self.t = 0.0
        self.service = DeskService(clock=lambda: self.t)
        self.service.features.wall_clock = lambda: 1000 + self.t
        self.ingress = PostureIngress(0)

    def tearDown(self):
        self.ingress.close()
        self.service.close()

    def sample(self, frame, captured=None, kind='camera', classification='bad', session='test'):
        return dict(source='detector', classification=classification, source_kind=kind,
                    session_id=session, frame_id=frame,
                    captured_at=1000 + self.t if captured is None else captured)

    def feed(self, **kwargs):
        self.ingress.submit(self.sample(**kwargs))
        return self.ingress.drain(self.service)[0]

    def test_same_service_emits_event_and_keeps_capture_provenance(self):
        for frame, t in enumerate((0, 5, 10)):
            self.t = t
            result = self.feed(frame=frame)
        self.assertTrue(result['reminded'])
        events = self.service.poll_events()
        self.assertEqual(events[0]['name'], 'posture.bad')
        self.assertEqual(events[0]['data']['captured_at'], 1010)
        self.assertEqual(self.service.execute('posture.status', {})['sample']['frame_id'], 2)
        self.assertEqual(self.service.poll_events(), [])

    def test_repeated_frame_and_out_of_order_never_accumulate(self):
        self.feed(frame=10)
        for t in (5, 10, 15):
            self.t = t
            self.assertTrue(self.feed(frame=10)['ignored'])
            self.assertTrue(self.feed(frame=9)['ignored'])
        self.assertEqual(self.service.poll_events(), [])
        self.assertTrue(self.service.execute('posture.status', {})['stale'])

    def test_offline_never_reminds_even_with_new_frame_ids(self):
        for kind in ('image', 'video'):
            for frame in range(4):
                self.t += 5
                result = self.feed(frame=frame, kind=kind, session=kind)
                self.assertEqual(result['classification'], 'unknown')
        self.assertEqual(self.service.poll_events(), [])

    def test_old_future_samples_and_capture_gap_reset(self):
        self.feed(frame=0)
        self.t = 5
        self.feed(frame=1)
        self.t = 10
        self.assertEqual(self.feed(frame=2, captured=1003)['classification'], 'unknown')
        self.assertEqual(self.feed(frame=3, captured=1020)['classification'], 'unknown')
        self.t = 21
        self.assertFalse(self.feed(frame=4)['reminded'])
        self.assertEqual(self.service.poll_events(), [])

    def test_receipt_burst_cannot_substitute_for_capture_duration(self):
        self.t = 10
        for frame in range(12):
            result = self.feed(frame=frame, captured=1009 + frame / 100)
        self.assertFalse(result['reminded'])
        self.assertEqual(self.service.poll_events(), [])

    def test_unknown_reset_cooldown_and_session_change(self):
        self.service.execute('posture.config', dict(duration=1, cooldown=10, max_gap=5))
        self.feed(frame=0)
        self.t = 1
        self.assertTrue(self.feed(frame=1)['reminded'])
        self.t = 2
        self.assertFalse(self.feed(frame=2)['reminded'])
        self.feed(frame=3, classification='unknown', captured=1002.01)
        self.t = 3
        self.assertFalse(self.feed(frame=4)['reminded'])
        self.t = 4
        self.assertFalse(self.feed(frame=0, session='new')['reminded'])

    def test_http_is_queued_then_main_thread_drains_and_no_event_theft(self):
        self.ingress.start()
        body = json.dumps(self.sample(frame=0)).encode()
        req = Request(f'http://127.0.0.1:{self.ingress.port}/posture/sample', data=body,
                      headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=3) as response:
            self.assertEqual(response.status, 202)
            self.assertFalse(json.load(response)['processed'])
        self.assertIsNone(self.service.features.last_sample)
        self.assertEqual(self.ingress.drain(self.service)[0]['classification'], 'bad')
        self.assertIsNotNone(self.service.features.last_sample)

    def test_synthetic_rules_to_real_http_to_same_service_reminder(self):
        """Synthetic keypoints + fake time, not measured human accuracy."""
        from posture_detection.rules import calibrate, classify, extract_features
        from posture_detection.test_rules import landmarks
        points = landmarks()
        baseline = calibrate([extract_features(points, (640, 480), 'front')
                              for _ in range(15)], 'front')
        self.assertEqual(classify(points, (640, 480), baseline)['classification'], 'good')
        points[0]['y'] += .12
        self.ingress.start()
        for frame, timestamp in enumerate((0, 5, 10)):
            self.t = timestamp
            detection = classify(points, (640, 480), baseline)
            self.assertEqual(detection['classification'], 'bad')
            payload = self.sample(frame=frame, classification=detection['classification'])
            payload.update({key: detection[key] for key in ('confidence', 'reasons', 'metrics')})
            request = Request(f'http://127.0.0.1:{self.ingress.port}/posture/sample',
                              data=json.dumps(payload).encode(),
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 202)
                self.assertFalse(json.load(response)['processed'])
            results = self.ingress.drain(self.service)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['reminded'], timestamp == 10)
            if timestamp < 10:
                self.assertEqual(self.service.poll_events(), [])
        event = self.service.poll_events()
        self.assertEqual(len(event), 1)
        self.assertEqual(event[0]['name'], 'posture.bad')
        self.assertEqual(event[0]['data']['source'], 'detector')
        self.assertEqual(event[0]['data']['captured_at'], 1010)
        self.assertEqual(event[0]['data']['frame_id'], 2)

    def test_invalid_metadata(self):
        for updates in ({'frame_id': True}, {'captured_at': float('nan')},
                        {'session_id': ''}, {'source': 'voice'}, {'source_kind': 'remote'}):
            params = self.sample(frame=0)
            params.update(updates)
            with self.assertRaises(ValueError):
                self.ingress.submit(params)
        self.assertEqual(self.ingress.drain(self.service), [])

    def test_queue_is_bounded(self):
        from queue import Full
        self.ingress.close()
        self.ingress = PostureIngress(0, queue_limit=1)
        self.ingress.submit(self.sample(frame=0))
        with self.assertRaises(Full):
            self.ingress.submit(self.sample(frame=1))
        self.assertEqual(len(self.ingress.drain(self.service)), 1)


if __name__ == '__main__':
    unittest.main()
