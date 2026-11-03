import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from ocr_link.client import NetworkError
from voice_bridge.pynq_service import DeskService, MAX_FRAME, encode, compact_book_evidence
from voice_bridge.remote_book_adapter import RemoteBookAdapter


class FakeClient:
    def __init__(self, *, blocked=False, wrong_hash=False, fail=False, text='高等数学', wrong_identity=None):
        self.calls = []
        self.release = threading.Event()
        self.entered = threading.Event()
        if not blocked:
            self.release.set()
        self.wrong_hash, self.fail, self.text = wrong_hash, fail, text
        self.wrong_identity = wrong_identity

    def run(self, payload, output, download_preview=True):
        self.calls.append(payload)
        self.entered.set()
        if not self.release.wait(2):
            raise TimeoutError('test backend timeout')
        if self.fail:
            raise NetworkError('do not send secret transport details over UART')
        state = dict(v=1, request_id=payload['request_id'], status='succeeded', result={
            'found': True, 'matches': [dict(text=self.text, match_score=1.0,
                                          book_box=[1, 2, 100, 200], normalized_center=[0.5, 0.5],
                                          private_path='secret', huge_extra='z' * 50000)] * 20,
            'image_sha256': 'wrong' if self.wrong_hash else payload['image']['sha256'],
            'request_id': payload['request_id'], 'action': payload['action'],
            'source': dict(payload['source']),
            'indicator_lit': True, 'motor_action': True,
            'timing': {'capture_age_at_result_seconds': 3.0}})
        if self.wrong_identity == 'state_id':
            state['request_id'] = 'another-request'
        if self.wrong_identity == 'result_id':
            state['result']['request_id'] = 'another-request'
        if self.wrong_identity == 'action':
            state['result']['action'] = 'book.scan'
        if self.wrong_identity == 'source':
            state['result']['source']['capture_id'] = 'another-capture'
        return state


class RemoteBookTests(unittest.TestCase):
    def test_geometry_review_summary_survives_remote_and_uart_without_claiming_inventory(self):
        class QualityClient(FakeClient):
            count=5
            def run(self,*args,**kwargs):
                state=super().run(*args,**kwargs)
                state['result'].update(spine_count=7,geometry_quality_evaluated=True,
                                       geometry_review_required_count=self.count)
                return state
        client=QualityClient()
        evidence=self.adapter(client).find('书',self.image)
        compact=compact_book_evidence(evidence)
        self.assertEqual(compact['geometry_review_required_count'],5)
        self.assertEqual(compact['spine_count'],7)
        self.assertEqual(compact['match_count'],20)
        self.assertFalse(compact['motor_action'])
        self.assertLessEqual(len(encode(dict(v=1,type='result',id='a',status='success',data=compact)))-1,MAX_FRAME)
        for count in (-1,8,True,None):
            with self.subTest(count=count):
                client.count=count
                with self.assertRaisesRegex(ValueError,'remote_book_result_invalid'):
                    self.adapter(client).find('书',self.image)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.image = self.root / 'image.jpg'
        self.image.write_bytes(b'\xff\xd8\xfffixture')

    def tearDown(self):
        self.temporary.cleanup()

    def adapter(self, client, **kwargs):
        return RemoteBookAdapter('http://localhost:1', None, client=client,
                                 output_root=self.root / 'reports', **kwargs)

    def request(self, action, params=None, rid='r1'):
        return dict(v=1, type='request', id=rid, action=action, params=params or {})

    def test_image_source_and_actuator_flags_are_owned_locally(self):
        client = FakeClient()
        result = self.adapter(client).find('高等数学', self.image, '中文 UART ID')
        self.assertFalse(result['source']['live'])
        self.assertEqual(result['source']['kind'], 'image')
        self.assertEqual(result['source']['freshness'], 'snapshot')
        self.assertEqual(result['source']['age_at_result_seconds'], 3)
        self.assertFalse(result['indicator_lit'])
        self.assertFalse(result['motor_action'])
        self.assertEqual(client.calls[0]['action'], 'book.find')
        self.assertEqual(client.calls[0]['params']['title'], '高等数学')
        self.assertNotEqual(client.calls[0]['request_id'], '中文 UART ID')

    def test_camera_recaptures_only_on_explicit_find(self):
        captures = []

        def capture(output):
            captures.append(output)
            return b'\xff\xd8\xfffixture', dict(kind='camera', capture_id='capture-1',
                       captured_at='2026-10-13T00:00:00+00:00', live=True,
                       age_seconds=0.1, clock='client_read_completion')

        client = FakeClient()
        adapter = self.adapter(client, camera='/dev/video0', capture=capture)
        self.assertEqual(captures, [])
        result = adapter.find('书')
        self.assertTrue(result['source']['live'])
        adapter.find('书')
        self.assertEqual(len(captures), 2)
        self.assertNotEqual(client.calls[0]['request_id'], client.calls[1]['request_id'])

    def test_wrong_image_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, 'remote_book_result_invalid'):
            self.adapter(FakeClient(wrong_hash=True)).find('书', self.image)

    def test_spine_count_is_distinct_from_text_region_count_and_bounded(self):
        class GroupedClient(FakeClient):
            count = 7
            def run(self, *args, **kwargs):
                state = super().run(*args, **kwargs)
                state['result']['spine_count'] = self.count
                return state
        client = GroupedClient()
        evidence = self.adapter(client).find('书', self.image)
        compact = compact_book_evidence(evidence)
        self.assertEqual(compact['spine_count'], 7)
        self.assertEqual(compact['match_count'], 20)
        self.assertEqual(compact['spine_count_semantics'], 'OCR_anchored_spine_hypotheses')
        self.assertLessEqual(len(json.dumps(compact,ensure_ascii=False).encode('utf-8')),1200)
        for count in (True, -1, 21):
            client.count = count
            with self.subTest(count=count), self.assertRaisesRegex(ValueError,'remote_book_result_invalid'):
                self.adapter(client).find('书', self.image)

    def test_wrong_state_result_action_or_capture_identity_rejected(self):
        for field in ('state_id', 'result_id', 'action', 'source'):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, 'remote_book_result_invalid'):
                    self.adapter(FakeClient(wrong_identity=field)).find('书', self.image)

    def test_worker_keeps_same_service_timer_and_bounded_return(self):
        client = FakeClient(blocked=True, text='中' * 10000)
        now = [0.0]
        service = DeskService(clock=lambda: now[0], book_image=str(self.image), book_adapter=self.adapter(client))
        feature_owner = service.features
        try:
            service.handle(self.request('timer.start', {'minutes': 1}, 'timer'))
            request = self.request('book.find', {'title': '书' * 200}, '😀' * 64)
            pending = service.handle(request)
            self.assertEqual(pending['status'], 'pending')
            self.assertTrue(client.entered.wait(1))
            self.assertEqual(service.handle(request), pending)
            self.assertEqual(len(client.calls), 1)
            now[0] = 60
            self.assertEqual(service.poll_events()[0]['name'], 'timer.finished')
            self.assertIs(service.features, feature_owner)
            client.release.set()
            deadline = time.monotonic() + 1
            final = None
            while time.monotonic() < deadline:
                events = service.poll_events()
                if events:
                    final = events[0]
                    break
                time.sleep(0.005)
            self.assertIsNotNone(final)
            self.assertEqual(final['status'], 'success')
            self.assertEqual(final['data']['match_count'], 20)
            self.assertTrue(final['data']['matches_truncated'])
            self.assertNotIn('huge_extra', json.dumps(final))
            self.assertNotIn('private_path', json.dumps(final))
            self.assertNotIn('path', final['data']['source'])
            self.assertLessEqual(len(encode(final)) - 1, MAX_FRAME)
            queried = service.handle(self.request('job.get', {'request_id': request['id']}, '😀' * 63 + 'a'))
            self.assertEqual(queried['status'], 'success')
            self.assertLessEqual(len(encode(queried)) - 1, MAX_FRAME)
            self.assertNotIn(b'response_too_large', encode(queried))
            self.assertEqual(service.handle(request), final)
            self.assertEqual(len(client.calls), 1)
        finally:
            client.release.set()
            service.close()

    def test_worker_failure_returns_stable_error(self):
        client = FakeClient(fail=True)
        service = DeskService(book_image=str(self.image), book_adapter=self.adapter(client))
        try:
            service.handle(self.request('book.find', {'title': '书'}))
            for _ in range(100):
                events = service.poll_events()
                if events:
                    break
                time.sleep(0.005)
            self.assertEqual(events[0]['error'], 'remote_book_unavailable')
            self.assertNotIn('secret', json.dumps(events[0]))
        finally:
            service.close()

    def test_default_unconnected_service_stays_local(self):
        service = DeskService()
        try:
            self.assertEqual(service.handle(self.request('book.find', {'title': '书'}))['error'], 'camera_and_locator_not_connected')
            self.assertEqual(service.handle(self.request('status', rid='status'))['data']['book_backend'], 'local')
        finally:
            service.close()


if __name__ == '__main__':
    unittest.main()
