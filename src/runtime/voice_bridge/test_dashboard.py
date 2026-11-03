import http.client
import json
import threading
import unittest
import uuid
from unittest.mock import patch

try:
    from .dashboard import DashboardServer
except ImportError:
    from dashboard import DashboardServer


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DashboardServer(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def send(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_home_and_missing_route(self):
        status, body = self.send('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('智能学习桌'.encode(), body)
        self.assertEqual(self.send('GET', '/missing')[0], 404)

    def test_protocol_and_simulated_light(self):
        payload = dict(v=1, type='request', id='web-light', action='light.scene', params=dict(scene='focus', brightness=30))
        status, body = self.send('POST', '/api/request', json.dumps(payload), {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result['status'], 'success')
        self.assertTrue(result['data']['simulated'])

    def test_reject_invalid_payload(self):
        self.assertEqual(self.send('POST', '/api/request', '{}')[0], 415)
        self.assertEqual(self.send('POST', '/api/request', 'not-json', {'Content-Type': 'application/json'})[0], 400)
        self.assertEqual(self.send('POST', '/api/request', 'x' * 2049, {'Content-Type': 'application/json'})[0], 413)

    def test_reject_cross_origin(self):
        self.assertEqual(self.send('GET', '/', headers={'Host': 'example.com'})[0], 403)
        self.assertEqual(self.send('POST', '/api/request', '{}', {'Content-Type': 'application/json', 'Origin': 'https://example.com'})[0], 403)

    def api(self, action, params=None):
        payload = dict(v=1, type='request', id=uuid.uuid4().hex, action=action, params=params or {})
        status, body = self.send('POST', '/api/request', json.dumps(payload), {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result['status'], 'success', result)
        return result['data']

    def test_timer_pause_resume_and_events(self):
        self.api('timer.start', {'minutes': 1})
        self.assertEqual(self.api('timer.pause')['state'], 'paused')
        self.assertEqual(self.api('timer.resume')['state'], 'running')
        self.api('timer.stop')
        self.assertEqual(self.api('timer.status')['state'], 'idle')
        status, body = self.send('GET', '/api/events')
        self.assertEqual(status, 200)
        self.assertIsInstance(json.loads(body)['events'], list)

    def test_exam_and_metadata_only_record(self):
        exam = self.api('exam.set', {'name': '期末考试', 'date': '2026-12-20'})
        self.assertTrue(exam['configured'])
        self.assertEqual(self.api('exam.get')['name'], '期末考试')
        self.api('exam.clear')
        record = self.api('paper.record.create', {'title': '数学试卷', 'location': '人工放入第一格'})
        self.assertFalse(record['physical_filing'])
        self.assertIn(record['id'], [item['id'] for item in self.api('paper.record.list')['records']])

    def test_book_job_returns_nested_final_result(self):
        module = self.server.service.__class__.__module__
        evidence = {'source': {'kind': 'offline_image', 'path': 'test.png'},
                    'matches': [{'text': '数学', 'normalized_center': [0.4, 0.5]}]}
        with patch(module + '.find_book', return_value=evidence):
            with self.server.service_lock:
                self.server.service.book_image = 'test.png'
            try:
                rid = uuid.uuid4().hex
                payload = dict(v=1, type='request', id=rid, action='book.find', params={'title': '数学'})
                status, body = self.send('POST', '/api/request', json.dumps(payload), {'Content-Type': 'application/json'})
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)['status'], 'pending')
                with self.server.service_lock:
                    self.server.service.jobs[rid]['future'].result(timeout=2)
                result = self.api('job.get', {'request_id': rid})
                self.assertEqual(result['status'], 'success')
                self.assertEqual(result['data']['matches'][0]['text'], '数学')
                self.assertEqual(result['id'], rid)
            finally:
                with self.server.service_lock:
                    self.server.service.book_image = None


if __name__ == '__main__':
    unittest.main()
