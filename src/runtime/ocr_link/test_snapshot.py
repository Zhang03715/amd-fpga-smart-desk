import unittest
from unittest.mock import MagicMock,patch
from .snapshot import read_snapshot
from .client import ClientError


class SnapshotTests(unittest.TestCase):
    def response(self,stamp='1000'):
        r=MagicMock();r.__enter__.return_value=r
        r.read.return_value=b'\xff\xd8test\xff\xd9'
        r.headers={'X-Captured-At':'2026-10-28T05:00:00+00:00','X-Captured-Monotonic':stamp,
                   'X-Width':'1920','X-Height':'1080','X-Camera-Device':'0','X-Sequence':'7'}
        return r

    def test_fresh_metadata_preserved(self):
        opener=MagicMock();opener.open.return_value=self.response()
        with patch('ocr_link.snapshot.build_opener',return_value=opener),patch('ocr_link.snapshot.time.monotonic',return_value=1001):
            data,info=read_snapshot('http://127.0.0.1:8766/snapshot')
            self.assertEqual(info['actual_width'],1920);self.assertEqual(info['sequence'],7)

    def test_stale_and_future_frames_rejected(self):
        for stamp in ('990','1002','nan'):
            opener=MagicMock();opener.open.return_value=self.response(stamp)
            with patch('ocr_link.snapshot.build_opener',return_value=opener),patch('ocr_link.snapshot.time.monotonic',return_value=1001):
                with self.assertRaises(ClientError):read_snapshot('http://127.0.0.1:8766/snapshot')

    def test_remote_camera_source_rejected(self):
        with self.assertRaises(ClientError):read_snapshot('http://192.0.2.10:8766/snapshot')
