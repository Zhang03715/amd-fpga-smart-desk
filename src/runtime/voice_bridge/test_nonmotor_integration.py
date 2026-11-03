import unittest
from unittest.mock import patch
from concurrent.futures import Future
try:
    from .pynq_service import DeskService, encode, MAX_FRAME
except ImportError:
    from pynq_service import DeskService, encode, MAX_FRAME

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.service = DeskService(simulate=True, clock=lambda: self.now)
        self.index = 0
    def tearDown(self): self.service.close()
    def send(self, action, params=None):
        self.index += 1
        return self.service.handle(dict(v=1, type='request', id=str(self.index), action=action, params=params or {}))

    def test_pause_resume_preserves_remaining(self):
        self.send('timer.start', {'minutes': 1})
        self.now = 10
        self.assertEqual(self.send('timer.pause')['data']['remaining_seconds'], 50)
        self.now = 100
        self.assertEqual(self.service.poll_events(), [])
        self.send('timer.resume')
        self.now = 149
        self.assertEqual(self.send('timer.status')['data']['remaining_seconds'], 1)
        self.now = 150
        self.assertEqual(self.service.poll_events()[0]['name'], 'timer.finished')

    def test_record_and_exam_not_physical(self):
        record = self.send('paper.record.create', {'title': '数学卷'})
        self.assertFalse(record['data']['physical_filing'])
        self.assertEqual(self.send('exam.set', {'name': '考试', 'date': '2027-06-07'})['status'], 'success')
        self.assertEqual(self.send('paper.file')['status'], 'failed')

    def test_light_off_and_invalid_rgb(self):
        self.assertFalse(self.send('light.scene', {'scene': 'off', 'brightness': 90})['data']['applied'])
        self.assertEqual(self.service.light_state['brightness'], 0)
        self.assertEqual(self.send('light.scene', {'scene': 'focus', 'rgb': [True, 0, 0]})['status'], 'failed')

    def test_async_book_does_not_block_timer_and_deduplicates(self):
        self.service.book_image = 'explicit.jpg'
        future = Future()
        with patch.object(self.service.worker, 'submit', return_value=future) as submit:
            request = dict(v=1, type='request', id='book', action='book.find', params={'title': '数学'})
            self.assertEqual(self.service.handle(request)['status'], 'pending')
            self.service.handle(request)
            submit.assert_called_once()
            self.assertEqual(self.send('timer.start', {'minutes': 1})['status'], 'success')
            future.set_result(dict(found=False, matches=[], source={'kind': 'offline_image', 'path': 'explicit.jpg'}, indicator_lit=False))
            messages = self.service.poll_events()
            self.assertEqual(messages[0]['id'], 'book')
            self.assertEqual(self.service.handle(request)['status'], 'success')
            self.assertFalse(self.service.handle(request)['data']['indicator_lit'])

    def test_oversized_response_is_bounded(self):
        wire = encode(dict(v=1, type='result', id='x', status='success', data='中'*1000))
        self.assertLessEqual(len(wire), MAX_FRAME + 1)
        self.assertIn(b'response_too_large', wire)

if __name__ == '__main__': unittest.main()
