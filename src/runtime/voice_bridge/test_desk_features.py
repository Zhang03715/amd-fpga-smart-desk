import tempfile
from datetime import datetime
from pathlib import Path
import unittest

from desk_features import FeatureService


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.time = 0
        self.service = FeatureService(now=lambda: datetime(2026, 10, 5), clock=lambda: self.time)

    def tearDown(self):
        self.service.close()

    def test_record_persistence_and_kind_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'records.db'
            service = FeatureService(path)
            item = service.execute('paper.record.create', {'title': '数学试卷', 'location': '人工标注第一格'})
            self.assertFalse(item['physical_filing'])
            service.close()
            service = FeatureService(path)
            self.assertEqual(service.execute('paper.record.get', {'id': item['id']})['title'], '数学试卷')
            with self.assertRaisesRegex(ValueError, 'record_not_found'):
                service.execute('wrong_question.get', {'id': item['id']})
            service.close()

    def test_wrong_question_crud_and_filter(self):
        item = self.service.execute('wrong_question.create', {'title': '方程', 'subject': '数学'})
        updated = self.service.execute('wrong_question.update', {'id': item['id'], 'resolved': True})
        self.assertTrue(updated['resolved'])
        self.assertEqual(len(self.service.execute('wrong_question.list', {'resolved': True})['records']), 1)
        self.assertEqual(self.service.execute('wrong_question.list', {'subject': '英语'})['records'], [])
        self.service.execute('wrong_question.delete', {'id': item['id']})
        with self.assertRaisesRegex(ValueError, 'record_not_found'):
            self.service.execute('wrong_question.get', {'id': item['id']})

    def test_invalid_record_parameters(self):
        for params in ({'title': ''}, {'title': 'x', 'resolved': 1}, {'title': 'x', 'notes': 'n' * 201}):
            with self.assertRaises(ValueError):
                self.service.execute('paper.record.create', params)
        for params in ({'limit': True}, {'limit': 4}, {'offset': -1}):
            with self.assertRaises(ValueError):
                self.service.execute('paper.record.list', params)
        with self.assertRaises(ValueError):
            self.service.execute('paper.record.get', {'id': True})

    def test_exam_dates(self):
        for target, days, state in (('2026-10-06', 1, 'upcoming'), ('2026-10-05', 0, 'today'), ('2026-10-04', -1, 'passed')):
            result = self.service.execute('exam.set', {'name': '考试', 'date': target})
            self.assertEqual((result['days_remaining'], result['state']), (days, state))
        for invalid in ('2026-02-30', '20261006', '2026-1-1'):
            with self.assertRaisesRegex(ValueError, 'invalid_exam_date'):
                self.service.execute('exam.set', {'name': '考试', 'date': invalid})
        self.assertFalse(self.service.execute('exam.clear', {})['configured'])

    def sample(self, timestamp, classification='bad'):
        self.time = timestamp
        return self.service.execute('posture.update', {'classification': classification, 'source': 'test'})

    def test_posture_continuity_cooldown_and_staleness(self):
        for t in (0, 5):
            self.assertFalse(self.sample(t)['reminded'])
        self.assertTrue(self.sample(10)['reminded'])
        self.assertEqual(self.service.poll_events()[0]['name'], 'posture.bad')
        self.assertEqual(self.service.poll_events(), [])
        for t in range(15, 70, 5):
            self.assertFalse(self.sample(t)['reminded'])
        self.assertTrue(self.sample(70)['reminded'])
        self.time = 80
        self.assertTrue(self.service.execute('posture.status', {})['stale'])
        self.service.poll_events()
        self.assertEqual(self.service.poll_events(), [])
        self.assertFalse(self.sample(100)['reminded'])

    def test_unknown_good_and_missing_samples_reset_bad(self):
        self.sample(0)
        self.sample(5, 'unknown')
        self.sample(10)
        self.assertFalse(self.sample(15)['reminded'])
        self.sample(20, 'good')
        self.sample(25)
        self.assertFalse(self.sample(36)['reminded'])

    def test_queue_bounded_and_config_validation_atomic(self):
        service = FeatureService(clock=lambda: self.time, event_limit=2)
        service.execute('posture.config', {'duration': 1, 'cooldown': 1})
        for t in range(5):
            self.time = t
            service.execute('posture.update', {'classification': 'bad'})
        self.assertEqual(len(service.poll_events()), 2)
        with self.assertRaises(ValueError):
            service.execute('posture.config', {'duration': 2, 'cooldown': float('nan')})
        self.assertEqual(service.duration, 1)
        service.close()


if __name__ == '__main__':
    unittest.main()
