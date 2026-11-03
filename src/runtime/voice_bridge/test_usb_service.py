import json
import tempfile
import unittest
from pathlib import Path
from .usb_service import USBSession
from .pynq_service import DeskService, encode


class USBTests(unittest.TestCase):
    def test_real_service_roundtrip_and_unrelated_probe(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DeskService(db_path=str(Path(folder)/'desk.sqlite3'))
            wire = []
            try:
                session = USBSession(service, wire.append)
                session.hello()
                request = encode(dict(v=1, type='request', id='s3-request',
                                      action='protocol.info', params={}))
                for byte in b'ROM boot noise\n' + request:
                    session.feed(bytes([byte]))
                result = json.loads(wire[-2])
                self.assertEqual(result['status'], 'success')
                self.assertEqual(result['id'], 's3-request')
                session.feed(encode(dict(v=1, type='hello', id='wrong',
                                        last_result_id='s3-request', last_result_status='success')))
                self.assertFalse(session.confirmed)
                session.feed(encode(dict(v=1, type='hello', id=session.probe_id,
                                        last_result_id='s3-request', last_result_status='success')))
                self.assertTrue(session.confirmed)
            finally:
                service.close()

    def test_overflow_does_not_execute_tail_and_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DeskService(db_path=str(Path(folder)/'desk.sqlite3'))
            wire = []
            try:
                session = USBSession(service, wire.append)
                request = encode(dict(v=1, type='request', id='test', action='status', params={}))
                session.feed(b'x'*4000 + request)
                self.assertEqual(wire, [])
                session.feed(request)
                self.assertEqual(json.loads(wire[0])['status'], 'success')
            finally:
                service.close()


class NativeUSBControlTests(unittest.TestCase):
    def test_reset_lines_released_before_open(self):
        from voice_bridge.usb_service import open_native_usb
        observed = []
        class Port:
            def __init__(self, port, *args, **kwargs):
                observed.append(port)
                self.dtr = True
                self.rts = True
            def open(self):
                observed.append((self.port, self.dtr, self.rts))
        class SerialModule:
            Serial = Port
        open_native_usb(SerialModule, '/dev/ttyACM0')
        self.assertEqual(observed, [None, ('/dev/ttyACM0', False, False)])

if __name__ == '__main__':
    unittest.main()
