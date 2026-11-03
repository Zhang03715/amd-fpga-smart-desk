import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .client import ClientError, NetworkError, OCRClient, make_request, read_token


class ClientTests(unittest.TestCase):
    def payload(self, request_id='sample-1'):
        return make_request(b'\xff\xd8\xfffixture', request_id, 'book.scan', None,
                            dict(kind='image', capture_id='capture_1', captured_at=None,
                                 live=False, age_seconds=0.0, clock='unknown'))

    def test_source_hash_and_action_boundary(self):
        payload = self.payload()
        self.assertEqual(base64.b64decode(payload['image']['data']), b'\xff\xd8\xfffixture')
        self.assertEqual(len(payload['image']['sha256']), 64)
        self.assertFalse(payload['source']['live'])
        with self.assertRaises(ClientError):
            make_request(b'\xff\xd8\xfffixture', 'bad/../id', 'book.scan', None, payload['source'])
        with self.assertRaises(ClientError):
            make_request(b'\xff\xd8\xfffixture', 'id', 'motor.move', None, payload['source'])
        with self.assertRaises(ClientError):
            make_request(b'\xff\xd8\xfffixture', 'id', 'book.scan', None, dict(payload['source'], live=True))
        with self.assertRaises(ClientError):
            make_request(b'\xff\xd8\xfffixture', 'id', 'book.scan', None, dict(payload['source'], age_seconds=float('nan')))

    def test_token_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'token'
            path.write_text('private-token\n')
            path.chmod(0o600)
            self.assertEqual(read_token(path), 'private-token')
            if os.name != 'nt':
                path.chmod(0o644)
                with self.assertRaises(ClientError):
                    read_token(path)

    def test_actual_http_authenticated_roundtrip(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, value, status=200, binary=False):
                body = value if binary else json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def authenticated(self):
                requests.append((self.command, self.path, self.headers.get('Authorization')))
                if self.headers.get('Authorization') != 'Bearer private-token':
                    self.send({'error': 'unauthorized'}, 401)
                    return False
                return True

            def do_POST(self):
                if not self.authenticated():
                    return
                self.server.payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send(dict(v=1, request_id='sample-1', status='queued'), 202)

            def do_GET(self):
                if not self.authenticated():
                    return
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/v1/health')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                elif self.path.endswith('/preview'):
                    self.send(b'\xff\xd8\xffpreview', binary=True)
                elif self.path == '/v1/health':
                    self.send(dict(v=1, status='ready'))
                else:
                    self.send(dict(v=1, request_id='sample-1', status='succeeded', result={'books': []}))

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                client = OCRClient(origin, 'private-token', poll_interval=0.01)
                self.assertEqual(client.health()['status'], 'ready')
                response = client.run(self.payload(), temporary)
                self.assertEqual(response['status'], 'succeeded')
                self.assertEqual(server.payload, self.payload())
                self.assertTrue((Path(temporary) / 'preview.jpg').exists())
                transport = json.loads((Path(temporary) / 'transport.json').read_text())
                self.assertGreaterEqual(transport['client_total_seconds'], transport['upload_seconds'])
                self.assertNotIn('private-token', json.dumps(transport))
                before = len(requests)
                with self.assertRaisesRegex(ClientError, 'HTTP 302'):
                    client._http('/redirect', time.monotonic() + 1)
                self.assertEqual(len(requests), before + 1, 'bearer token must not follow redirects')
                with self.assertRaisesRegex(ClientError, 'HTTP 401'):
                    OCRClient(origin, 'wrong-token').health()
                self.assertTrue(all(token == 'Bearer private-token' for _, _, token in requests[:-1]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_upload_and_poll_network_retry_keep_same_request(self):
        calls = []

        class Flaky(OCRClient):
            def _http(self, path, deadline, payload=None, binary=False):
                calls.append((path, payload))
                count = sum(1 for p, _ in calls if p == path)
                if count == 1:
                    raise NetworkError('transient')
                return dict(v=1, request_id='sample-1', status='queued' if payload else 'succeeded', result={})

        with tempfile.TemporaryDirectory() as temporary:
            payload = self.payload()
            response = Flaky('http://127.0.0.1:1', 'token', poll_interval=0.001).run(payload, temporary, False)
            self.assertEqual(response['status'], 'succeeded')
            uploads = [body for _, body in calls if body is not None]
            self.assertEqual(uploads, [payload, payload])
            trace = json.loads((Path(temporary) / 'transport.json').read_text())
            self.assertEqual(trace['network_retries'], 2)

    def test_timeout_preserves_request_for_resume(self):
        class Down(OCRClient):
            def _http(self, *args, **kwargs):
                raise NetworkError('offline')

        with tempfile.TemporaryDirectory() as temporary:
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                Down('http://127.0.0.1:1', 'token', total_timeout=0.03, poll_interval=0.005).run(self.payload(), temporary)
            self.assertLess(time.monotonic() - start, 1)
            self.assertEqual(json.loads((Path(temporary) / 'request.json').read_text()), self.payload())
            trace = json.loads((Path(temporary) / 'transport.json').read_text())
            self.assertEqual(trace['status'], 'transport_failed')

    def test_per_request_budget_does_not_mutate_client_default(self):
        class Down(OCRClient):
            def _http(self,*args,**kwargs):raise NetworkError('offline')
        client=Down('http://127.0.0.1:1','token',total_timeout=5,poll_interval=.005)
        with tempfile.TemporaryDirectory() as folder:
            start=time.monotonic()
            with self.assertRaises(TimeoutError):client.run(self.payload(),folder,total_timeout=.03)
            self.assertLess(time.monotonic()-start,1)
            self.assertEqual(client.total_timeout,5)

    def test_resume_does_not_replace_existing_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'request.json'
            path.write_text(json.dumps(self.payload('first')))
            with self.assertRaisesRegex(ClientError, 'different request'):
                OCRClient('http://127.0.0.1:1', 'token').run(self.payload('other'), temporary)
            self.assertEqual(json.loads(path.read_text())['request_id'], 'first')

    def test_wrong_job_identity_on_upload_or_poll_is_rejected(self):
        class Mixed(OCRClient):
            def __init__(self, wrong_on_upload):
                super().__init__('http://127.0.0.1:1', 'token', poll_interval=0.001)
                self.wrong_on_upload = wrong_on_upload
            def _http(self, path, deadline, payload=None, binary=False):
                if payload is not None and not self.wrong_on_upload:
                    return dict(v=1, request_id='sample-1', status='queued')
                return dict(v=1, request_id='other-job', status='succeeded', result={})

        for wrong_on_upload in (True, False):
            with self.subTest(wrong_on_upload=wrong_on_upload), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(ClientError, 'invalid job state'):
                    Mixed(wrong_on_upload).run(self.payload(), temporary, False)


if __name__ == '__main__':
    unittest.main()
