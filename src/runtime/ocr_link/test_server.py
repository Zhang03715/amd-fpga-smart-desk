"""Real HTTP protocol tests with a controlled fake; no CUDA, cameras or board."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

from .client import OCRClient, make_request
from .server import JobStore, make_handler


TOKEN = 'test-private-token'


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.calls = []
        self.requests = []
        self.gate = threading.Event()
        self.gate.set()
        self.started = threading.Event()
        self.failure = None
        self.image = self.encoded('PNG')
        self.preview = self.encoded('JPEG')
        self.app = JobStore(self.root, self.fake_pipeline, max_pending=2, max_jobs=8)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app, TOKEN))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        self.app.close()
        self.temporary.cleanup()

    @staticmethod
    def encoded(fmt):
        stream = io.BytesIO()
        Image.new('RGB', (16, 12), (40, 60, 80)).save(stream, format=fmt)
        return stream.getvalue()

    def fake_pipeline(self, image_path, request, output_dir):
        self.calls.append(request['request_id'])
        self.requests.append(request)
        self.started.set()
        if not self.gate.wait(4):
            raise TimeoutError('test synchronization timed out')
        if self.failure is not None:
            raise self.failure
        self.assertEqual(hashlib.sha256(Path(image_path).read_bytes()).hexdigest(), request['image']['sha256'])
        Path(output_dir, 'preview.jpg').write_bytes(self.preview)
        return {'regions': [{'title': '高等数学', 'confidence': 0.97,
                             'points': [[1, 2], [10, 2], [10, 8], [1, 8]],
                             'accepted': True}],
                'device': 'fake', 'no_hardware_actions': True}

    def payload(self, request_id='scan-1', action='book.scan', title=None):
        return make_request(self.image, request_id, action, title,
                            {'kind': 'image', 'capture_id': 'capture-1', 'captured_at': None,
                             'live': False, 'age_seconds': 0.0, 'clock': 'unknown'})

    def http(self, path, payload=None, *, token=TOKEN, raw=None, headers=None):
        body = raw if raw is not None else (json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None)
        actual_headers = {'Content-Type': 'application/json'}
        if token is not None:
            actual_headers['Authorization'] = 'Bearer ' + token
        actual_headers.update(headers or {})
        request = Request(self.origin + path, data=body, headers=actual_headers,
                          method='POST' if body is not None else 'GET')
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, response.read(), response.headers
        except HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def terminal(self, request_id):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            code, body, _ = self.http('/v1/jobs/' + request_id)
            self.assertEqual(code, 200, body)
            state = json.loads(body)
            if state['status'] in ('succeeded', 'failed'):
                return state
            time.sleep(0.01)
        self.fail('fake task did not reach terminal state')

    def test_authentication_on_every_endpoint(self):
        for token in (None, 'wrong-token'):
            for path in ('/v1/health', '/v1/jobs/scan-1', '/v1/jobs/scan-1/preview'):
                with self.subTest(token=token, path=path):
                    self.assertEqual(self.http(path, token=token)[0], 401)
            self.assertEqual(self.http('/v1/jobs', self.payload(), token=token)[0], 401)
        self.assertEqual(self.calls, [])
        code, body, _ = self.http('/v1/health')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['v'], 1)
        self.assertEqual(self.calls, [])  # Health alone never runs OCR.

    def test_scan_roundtrip_keeps_identity_geometry_and_preview(self):
        payload = self.payload()
        code, body, _ = self.http('/v1/jobs', payload)
        self.assertEqual(code, 202, body)
        self.assertEqual(json.loads(body)['request_id'], payload['request_id'])
        state = self.terminal(payload['request_id'])
        self.assertEqual(state['status'], 'succeeded', state)
        result = state['result']
        self.assertEqual(result['request_id'], payload['request_id'])
        self.assertEqual(result['image_sha256'], payload['image']['sha256'])
        self.assertEqual(result['source'], payload['source'])
        self.assertEqual(result['regions'][0]['title'], '高等数学')
        self.assertEqual(result['regions'][0]['points'][0], [1, 2])
        self.assertFalse(result['source']['live'])
        code, preview, headers = self.http('/v1/jobs/scan-1/preview')
        self.assertEqual(code, 200)
        self.assertEqual(preview, self.preview)
        self.assertTrue(headers['Content-Type'].startswith('image/jpeg'))

    def test_find_request_is_forwarded_exactly(self):
        payload = self.payload('find-1', 'book.find', '高等数学')
        self.assertEqual(self.http('/v1/jobs', payload)[0], 202)
        self.assertEqual(self.terminal('find-1')['status'], 'succeeded')
        self.assertEqual(self.requests[0]['params'], {'title': '高等数学'})

    def test_same_id_deduplicates_and_conflict_is_rejected(self):
        self.gate.clear()
        payload = self.payload()
        self.assertEqual(self.http('/v1/jobs', payload)[0], 202)
        self.assertTrue(self.started.wait(1))
        self.assertEqual(self.http('/v1/jobs', payload)[0], 202)
        changed = self.payload(action='book.find', title='高等数学')
        self.assertEqual(self.http('/v1/jobs', changed)[0], 409)
        self.gate.set()
        self.terminal('scan-1')
        self.assertEqual(self.http('/v1/jobs', payload)[0], 202)
        self.assertEqual(self.calls, ['scan-1'])

    def test_bounded_queue_rejects_excess_and_preserves_existing(self):
        self.gate.clear()
        self.assertEqual(self.http('/v1/jobs', self.payload('one'))[0], 202)
        self.assertTrue(self.started.wait(1))
        self.assertEqual(self.http('/v1/jobs', self.payload('two'))[0], 202)
        self.assertEqual(self.http('/v1/jobs', self.payload('three'))[0], 429)
        self.assertEqual(self.http('/v1/jobs', self.payload('one'))[0], 202)
        self.gate.set()
        self.assertEqual(self.terminal('one')['status'], 'succeeded')
        self.assertEqual(self.terminal('two')['status'], 'succeeded')
        self.assertEqual(self.calls, ['one', 'two'])

    def test_invalid_payloads_never_run_pipeline(self):
        cases = []
        for field, value in [('v', 99), ('request_id', '../escape'), ('action', 'motor.move')]:
            p = self.payload()
            p[field] = value
            cases.append(p)
        p = self.payload(); p['image']['sha256'] = '0' * 64; cases.append(p)
        p = self.payload(); p['image']['data'] = '**not-base64**'; cases.append(p)
        p = self.payload(); p['params'] = {'title': 'unwanted'}; cases.append(p)
        p = self.payload(); p['source']['live'] = True; cases.append(p)
        p = self.payload(); p['source']['age_seconds'] = -1; cases.append(p)
        p = self.payload(); p['source']['age_seconds'] = float('nan'); cases.append(p)
        p = self.payload(); p['source']['clock'] = 'made-up'; cases.append(p)
        p = self.payload(); p['source']['kind'] = 'sensor'; cases.append(p)
        p = self.payload(); p['source']['captured_at'] = 'not-an-iso-time'; cases.append(p)
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.http('/v1/jobs', payload)[0], 400)
        self.assertEqual(self.http('/v1/jobs', raw=b'{broken')[0], 400)
        self.assertEqual(self.http('/v1/jobs', raw=b'[]')[0], 400)
        self.assertEqual(self.calls, [])

    def test_corrupt_image_with_valid_sha_is_rejected(self):
        raw = b'\xff\xd8\xffnot-a-real-jpeg'
        payload = self.payload()
        payload['image'].update(data=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.http('/v1/jobs', payload)[0], 400)
        self.assertEqual(self.calls, [])

    def test_payload_length_limit_rejects_before_decode(self):
        # Deliberately exceeds the maximum base64 envelope (~11.2 MiB).
        code, _, _ = self.http('/v1/jobs', raw=b'x', headers={'Content-Length': str(32 * 1024 * 1024)})
        self.assertEqual(code, 413)
        self.assertEqual(self.calls, [])

    def test_pipeline_failure_and_timeout_are_terminal(self):
        for request_id, error in [('failed-1', RuntimeError('fake_processing_failed')),
                                  ('timed-1', TimeoutError('fake_deadline_expired'))]:
            self.failure = error
            self.assertEqual(self.http('/v1/jobs', self.payload(request_id))[0], 202)
            state = self.terminal(request_id)
            self.assertEqual(state['status'], 'failed')
            self.assertIn('error', state)
            self.assertNotIn('result', state)
            code, raw, _ = self.http('/v1/jobs/' + request_id + '/preview')
            self.assertIn(code, (404, 409))
            self.assertFalse(raw.startswith(b'\xff\xd8\xff'))

    def test_expired_running_and_queued_jobs_have_no_result(self):
        fake_clock = [1000.0]
        self.app.clock = lambda: fake_clock[0]
        self.gate.clear()
        self.assertEqual(self.http('/v1/jobs', self.payload('expires-running'))[0], 202)
        self.assertTrue(self.started.wait(1))
        self.assertEqual(self.http('/v1/jobs', self.payload('expires-queued'))[0], 202)
        fake_clock[0] += 200
        self.gate.set()
        for request_id in ('expires-running', 'expires-queued'):
            state = self.terminal(request_id)
            self.assertEqual(state['status'], 'failed')
            self.assertNotIn('result', state)
            self.assertIn(self.http('/v1/jobs/' + request_id + '/preview')[0], (404, 409))
        self.assertEqual(self.calls, ['expires-running'])

    def test_unknown_and_traversal_paths_do_not_expose_files(self):
        for path in ('/v1/jobs/missing', '/v1/jobs/missing/preview',
                     '/v1/jobs/..%2fsecret', '/v1/jobs/../secret/preview', '/not-an-endpoint'):
            with self.subTest(path=path):
                self.assertIn(self.http(path)[0], (400, 404))

    def test_restart_restores_terminal_without_rerunning_and_marks_inflight_failed(self):
        payload = self.payload('persisted-terminal')
        self.assertEqual(self.http('/v1/jobs', payload)[0], 202)
        first = self.terminal('persisted-terminal')
        self.assertEqual(first['status'], 'succeeded')
        self.app.close()
        restored = JobStore(self.root, self.fake_pipeline)
        try:
            self.assertEqual(restored.status('persisted-terminal'), first)
            self.assertEqual(restored.submit(payload), first)
            self.assertEqual(restored.preview('persisted-terminal').read_bytes(), self.preview)
            self.assertEqual(self.calls, ['persisted-terminal'])
        finally:
            restored.close()
        # Simulate the persisted state left by an interrupted worker, with no
        # actual process termination or runaway fake thread in this test.
        path = self.root / 'persisted-terminal' / 'response.json'
        path.write_text(json.dumps({'v': 1, 'request_id': 'persisted-terminal', 'status': 'running'}))
        restarted = JobStore(self.root, self.fake_pipeline)
        try:
            state = restarted.status('persisted-terminal')
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['error'], 'ServerRestart')
            self.assertNotIn('result', state)
            self.assertEqual(restarted.submit(payload), state)
            self.assertEqual(self.calls, ['persisted-terminal'])
        finally:
            restarted.close()

    def test_terminal_storage_capacity_does_not_drop_old_results(self):
        self.app.max_jobs = 1
        first_payload = self.payload('retained')
        self.assertEqual(self.http('/v1/jobs', first_payload)[0], 202)
        first = self.terminal('retained')
        self.assertEqual(first['status'], 'succeeded')
        self.assertEqual(self.http('/v1/jobs', self.payload('excess'))[0], 202)
        self.assertEqual(self.terminal('excess')['status'],'succeeded')
        self.assertLessEqual(len(self.app.jobs),1)
        self.assertEqual(self.http('/v1/jobs', first_payload)[0], 202)
        self.assertEqual(self.terminal('retained'), first)
        self.assertEqual(self.calls, ['retained','excess'])
        changed=self.payload('retained','book.find','高等数学')
        self.assertEqual(self.http('/v1/jobs',changed)[0],409)
        self.assertEqual(self.http('/v1/jobs/retained/preview')[0],200)
        self.assertTrue(list((self.root/'retained').glob('input.*')))

    def test_restart_with_more_disk_jobs_than_cache_still_accepts_work(self):
        self.app.max_jobs=1
        for rid in ('persist-one','persist-two'):
            self.assertEqual(self.http('/v1/jobs',self.payload(rid))[0],202)
            self.terminal(rid)
        self.app.close()
        restored=JobStore(self.root,self.fake_pipeline,max_jobs=1)
        try:
            self.assertEqual(restored.status('persist-two')['status'],'succeeded')
            self.assertEqual(restored.submit(self.payload('persist-two'))['status'],'succeeded')
            self.assertEqual(len(self.calls),2)
            self.assertEqual(restored.submit(self.payload('persist-three'))['status'],'queued')
        finally:restored.close()
        self.assertEqual(self.calls,['persist-one','persist-two','persist-three'])

    def test_real_server_with_production_client_saves_returned_result(self):
        client = OCRClient(self.origin, TOKEN, request_timeout=2, total_timeout=4, poll_interval=0.01)
        output = self.root / 'client-return'
        state = client.run(self.payload('client-1'), output)
        self.assertEqual(state['status'], 'succeeded')
        self.assertEqual(json.loads((output / 'response.json').read_text(encoding='utf-8')), state)
        self.assertEqual((output / 'preview.jpg').read_bytes(), self.preview)
        trace = json.loads((output / 'transport.json').read_text(encoding='utf-8'))
        self.assertEqual(trace['status'], 'succeeded')
        self.assertEqual(trace['network_retries'], 0)
        self.assertGreaterEqual(trace['client_total_seconds'], trace['upload_seconds'])


if __name__ == '__main__':
    unittest.main()
