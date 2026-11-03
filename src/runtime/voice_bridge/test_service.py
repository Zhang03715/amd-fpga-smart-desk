import unittest
from pynq_service import DeskService, FrameDecoder, MAX_FRAME, encode

class ServiceTests(unittest.TestCase):
    def test_posture_red_persistence_recovery_stale_and_book_priority(self):
        class Adapter:
            def __init__(self): self.calls=[]
            def posture_alert(self, active): self.calls.append(active)
        adapter=Adapter()
        self.service.book_adapter=adapter
        features=self.service.features
        for second in range(11):
            self.now=second
            features.execute('posture.update', {'classification':'bad'})
            self.service.poll_events()
        self.assertEqual(adapter.calls,[True])
        self.now=11
        features.execute('posture.update', {'classification':'good'})
        self.service.poll_events()
        self.assertEqual(adapter.calls,[True,False])
        for second in range(12,23):
            self.now=second
            features.execute('posture.update', {'classification':'bad'})
            self.service.poll_events()
        self.assertEqual(adapter.calls[-1],True)
        self.now=100
        self.service.poll_events()
        self.assertEqual(adapter.calls[-1],False)
        self.service.posture_light_active=True
        self.service.jobs['busy']={'future':object()}
        self.service.update_posture_light()
        self.assertEqual(adapter.calls,[True,False,True,False])
        self.service.jobs.clear()

    def test_book_indicator_survives_timeout_and_restores_after_alert(self):
        class Adapter:
            def __init__(self):self.calls=[]
            def posture_alert(self,active):self.calls.append(('alert',active))
            def focus_countdown(self,pixels):self.calls.append('timer')
            def restore_indication(self):self.calls.append('restore')
        adapter=Adapter();self.service.book_adapter=adapter
        self.service.book_light_until=float('inf');self.now=300
        self.service.update_posture_light();self.assertEqual(adapter.calls,[])
        self.service.posture_light_active=True
        self.service.update_posture_light();self.assertEqual(adapter.calls,['restore'])
        self.assertFalse(self.service.posture_light_active)

    def setUp(self):
        self.now = 0
        self.service = DeskService(clock=lambda: self.now)

    def request(self, action, params=None, rid='1'):
        return self.service.handle(dict(v=1, type='request', id=rid, action=action, params=params or {}))

    def test_duplicate_does_not_restart_timer(self):
        first = self.request('timer.start', {'minutes': 1})
        self.now = 30
        self.assertEqual(self.request('timer.start', {'minutes': 1}), first)
        self.now = 60
        self.assertEqual(self.service.poll_events()[0]['name'], 'timer.finished')
        self.assertEqual(self.service.poll_events(), [])

    def test_id_conflict(self):
        self.request('timer.start')
        self.assertEqual(self.request('timer.stop')['error'], 'id_conflict')

    def test_no_fake_hardware_success(self):
        self.assertEqual(self.request('light.scene', {'scene': 'focus'})['status'], 'failed')
        self.assertEqual(self.request('book.find', {'title': '数学'}, rid='2')['status'], 'failed')

    def test_invalid_parameters(self):
        for index, minutes in enumerate((True, 0, 121, '25')):
            self.assertEqual(self.request('timer.start', {'minutes': minutes}, str(index))['status'], 'failed')

    def test_timer_stop(self):
        self.request('timer.start', {'minutes': 1})
        self.request('timer.stop', rid='2')
        self.now = 100
        self.assertEqual(self.service.poll_events(), [])

    def test_simulation_is_marked(self):
        self.service.simulate = True
        self.assertTrue(self.request('light.scene', {'scene': 'rest'})['data']['simulated'])

    def test_duplicate_retry_after_completion_does_not_restart(self):
        self.request('timer.start', {'minutes': 1})
        self.now = 60
        self.service.poll_events()
        self.request('timer.start', {'minutes': 1})
        self.assertEqual(self.service.timer_end, 360)
        self.assertEqual(self.service.timer_status()['phase'], 'rest')

    def test_timer_replacement_and_expired_status(self):
        self.request('timer.start', {'minutes': 1})
        self.now = 30
        self.request('timer.start', {'minutes': 2}, rid='2')
        self.now = 60
        self.assertEqual(self.service.poll_events(), [])
        self.now = 150
        self.assertFalse(self.request('status', rid='3')['data']['timer_active'])
        self.assertEqual(len(self.service.poll_events()), 1)

    def test_conflict_preserves_original_id(self):
        original = self.request('timer.start', {'minutes': 1})
        self.assertEqual(self.request('timer.stop')['error'], 'id_conflict')
        self.assertEqual(self.request('timer.start', {'minutes': 1}), original)

    def test_all_unconnected_actuators_fail(self):
        for index, action in enumerate(('light.scene', 'book.find', 'paper.file')):
            result = self.request(action, {'scene': 'focus', 'title': '数学'}, str(index))
            self.assertEqual(result['status'], 'failed')


class FramingTests(unittest.TestCase):
    def setUp(self):
        self.decoder = FrameDecoder(DeskService())
        self.valid = encode(dict(v=1, type='request', id='1', action='status', params={}))

    def test_split_and_multiple_frames(self):
        self.assertEqual(self.decoder.feed(self.valid[:20]), [])
        replies = self.decoder.feed(self.valid[20:] + self.valid)
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[0], replies[1])

    def test_exact_limit_lf_and_crlf(self):
        padded = self.valid[:-1] + b' ' * (MAX_FRAME - len(self.valid) + 1)
        for ending in (b'\n', b'\r\n'):
            self.assertEqual(self.decoder.feed(padded + ending)[0]['status'], 'success')

    def test_overflow_bounded_and_recovers(self):
        self.decoder.feed(b'x' * 100000)
        self.assertLessEqual(len(self.decoder.buffer), MAX_FRAME + 1)
        replies = self.decoder.feed(b'\n' + self.valid)
        self.assertEqual(replies[0]['error'], 'frame_too_large')
        self.assertEqual(replies[1]['status'], 'success')

    def test_multibyte_limit_counts_bytes(self):
        replies = self.decoder.feed(('中' * 700).encode() + b'\n')
        self.assertEqual(replies[0]['error'], 'frame_too_large')

    def test_bad_json_and_envelopes_recover(self):
        for frame in (b'{', b'\xff', b'[]', b'{"v":NaN}', b'{"v":1,"v":1}',
                      b'{"v":true,"type":"request","id":"1"}', b'[' * 1200):
            replies = self.decoder.feed(frame + b'\n' + self.valid)
            self.assertEqual(replies[0]['type'], 'error')
            self.assertEqual(replies[1]['status'], 'success')

if __name__ == '__main__': unittest.main()
