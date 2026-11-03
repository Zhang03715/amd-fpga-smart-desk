"""Freshness and process-boundary helpers, independent of model runtime."""
import hashlib
import json
import time
import urllib.request
from urllib.parse import urlparse


class FrozenFrameGuard:
    """Exact frozen pixels are conservatively unknown, even for a still person."""
    def __init__(self, timeout=2.0):
        self.timeout = timeout
        self.digest = None
        self.changed_at = None

    def frozen(self, image_bytes, captured_monotonic):
        digest = hashlib.sha256(image_bytes).digest()
        if digest != self.digest:
            self.digest, self.changed_at = digest, captured_monotonic
        return captured_monotonic - self.changed_at >= self.timeout


def send_sample(endpoint, sample):
    parsed = urlparse(endpoint)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path != '/posture/sample':
        raise ValueError('endpoint must be loopback http://127.0.0.1:PORT/posture/sample')
    request = urllib.request.Request(endpoint, json.dumps(sample, allow_nan=False).encode('utf-8'),
                                     {'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.load(response)


def unknown(reason):
    return {'classification': 'unknown', 'confidence': 0.0, 'reasons': [reason], 'metrics': {}}
