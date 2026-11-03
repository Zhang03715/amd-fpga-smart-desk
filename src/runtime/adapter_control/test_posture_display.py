import json
from pathlib import Path
import tempfile
import unittest
from adapter_control.posture_display import posture_label


class PostureDisplayTests(unittest.TestCase):
    def test_history_is_labelled_and_dead_producer_expires(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'status.json'
            record=dict(captured_monotonic=100,age_seconds=1.5,
                        assessment=dict(state='within_reference',reasons=[]))
            p.write_text(json.dumps(record))
            self.assertEqual(posture_label(p,101.8),'Pose: upright 1.8s')
            self.assertEqual(posture_label(p,103),'Last: upright 3.0s')
            self.assertEqual(posture_label(p,105),'Pose: waiting / stale')
            self.assertEqual(posture_label(p,101),'Pose: waiting / stale')
            record['age_seconds']=2.3
            record['assessment']=dict(state='unknown',reasons=['stale_frame'])
            p.write_text(json.dumps(record))
            self.assertEqual(posture_label(p,102.5),'Pose: inference too slow')

    def test_stale_normal_must_not_look_normal(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'status.json'
            self.assertEqual(posture_label(p,100), 'Pose: waiting')
            p.write_text(json.dumps({'captured_monotonic':100,
                                    'assessment':{'status':'within_reference'}}))
            self.assertEqual(posture_label(p,101), 'Pose: within reference')
            self.assertEqual(posture_label(p,103), 'Pose: waiting / stale')
            self.assertEqual(posture_label(p,99), 'Pose: waiting / stale')
            p.write_text('{broken')
            self.assertEqual(posture_label(p,100), 'Pose: waiting')
