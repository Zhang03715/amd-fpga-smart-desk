import io
import unittest
from PIL import Image
from .camera_preview import HEADER, decode_packet


class CameraPacketTests(unittest.TestCase):
    def packet(self, size=(320, 240), captured=100.0):
        stream = io.BytesIO()
        Image.new('RGB', size, 'red').save(stream, 'JPEG')
        return HEADER.pack(captured, 42)+stream.getvalue()

    def test_fresh_frame_timestamp_and_sequence(self):
        image, sequence, age = decode_packet(self.packet(), 100.25)
        self.assertEqual(image.size, (320, 240))
        self.assertEqual(sequence, 42)
        self.assertEqual(age, .25)

    def test_stale_future_bad_size_and_truncated_frames_rejected(self):
        for packet, now in [(self.packet(), 103), (self.packet(), 99),
                            (self.packet((1, 1)), 100), (b'bad', 100),
                            (HEADER.pack(100, 1)+b'bad', 100)]:
            with self.assertRaises((ValueError, OSError)):
                decode_packet(packet, now)


if __name__ == '__main__': unittest.main()
