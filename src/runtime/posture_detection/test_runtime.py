import unittest
from .runtime import FrozenFrameGuard, send_sample


class FreshnessTests(unittest.TestCase):
    def test_frozen_pixels_do_not_gain_freshness_from_new_ids(self):
        guard = FrozenFrameGuard(2)
        self.assertFalse(guard.frozen(b'same pixels', 10))
        self.assertFalse(guard.frozen(b'same pixels', 11))
        self.assertTrue(guard.frozen(b'same pixels', 12))
        self.assertFalse(guard.frozen(b'new pixels', 13))

    def test_remote_or_wrong_endpoint_rejected_before_network(self):
        for endpoint in ('http://example.com/posture/sample', 'https://127.0.0.1/posture/sample',
                         'http://127.0.0.1/api/request'):
            with self.assertRaises(ValueError): send_sample(endpoint, {})


if __name__ == '__main__': unittest.main()
