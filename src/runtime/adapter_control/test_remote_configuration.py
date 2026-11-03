from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .run import AdapterService, main


class RemoteConfigurationTests(unittest.TestCase):
    def invoke(self, arguments):
        owners = []
        def service_factory(**kwargs):
            service = AdapterService(**kwargs)
            owners.append(service)
            return service
        with tempfile.TemporaryDirectory() as temporary:
            preview = Path(temporary) / 'preview.png'
            with patch('adapter_control.run.load') as hardware_load, \
                 patch('adapter_control.run.AdapterService', side_effect=service_factory):
                main(['--once', '--preview', str(preview)] + arguments)
                self.assertTrue(preview.is_file())
                hardware_load.assert_not_called()
        self.assertEqual(len(owners), 1)
        return owners[0]

    def test_default_preserves_local_service(self):
        owner = self.invoke([])
        self.assertIsNone(owner.book_adapter)
        self.assertIsNone(owner.book_image)
        self.assertEqual(owner.execute('status', {})['book_backend'], 'local')

    def test_explicit_remote_image_config_reaches_same_service(self):
        with patch('voice_bridge.remote_book_adapter.RemoteBookAdapter') as constructor:
            constructor.return_value.camera = None
            owner = self.invoke(['--book-ocr-server', 'http://127.0.0.1:8787',
                                 '--book-ocr-token-file', 'private-token-file',
                                 '--book-image', 'books.jpg', '--book-ocr-timeout', '75'])
            self.assertIs(owner.book_adapter, constructor.return_value)
            self.assertEqual(owner.book_image, 'books.jpg')
            self.assertEqual(owner.execute('status', {})['book_backend'], 'remote_pc')
            constructor.assert_called_once_with('http://127.0.0.1:8787', 'private-token-file',
                camera=None, runtime_path=None, output_root='output/remote-book', total_timeout=75.0)
            constructor.return_value.find.assert_not_called()

    def test_explicit_camera_config_not_opened_on_startup(self):
        with patch('voice_bridge.remote_book_adapter.RemoteBookAdapter') as constructor:
            constructor.return_value.camera = '/dev/video2'
            owner = self.invoke(['--book-ocr-server', 'http://127.0.0.1:8787',
                                 '--book-ocr-token-file', 'private-token-file',
                                 '--book-camera', '/dev/video2', '--book-camera-runtime-path', '/existing/cv2'])
            self.assertEqual(owner.execute('status', {})['book_source'], 'camera_snapshot')
            constructor.return_value.find.assert_not_called()
            self.assertEqual(constructor.call_args.kwargs['runtime_path'], '/existing/cv2')

    def test_invalid_partial_config_rejected_before_hardware(self):
        with patch('adapter_control.run.load') as hardware_load, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(['--bitfile', 'should-not-load.bit', '--book-ocr-server', 'http://127.0.0.1:8787'])
            hardware_load.assert_not_called()

    def test_same_camera_preview_and_capture_rejected_before_hardware(self):
        with patch('voice_bridge.remote_book_adapter.RemoteBookAdapter'), \
             patch('adapter_control.run.load') as hardware_load, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(['--bitfile', 'should-not-load.bit', '--camera', '0',
                      '--book-ocr-server', 'http://127.0.0.1:8787',
                      '--book-ocr-token-file', 'private-token-file', '--book-camera', '/dev/video0'])
            hardware_load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
