"""Real OCR regression, including absent title, invalid image and timeout."""
from pathlib import Path
import tempfile
import unittest

from voice_bridge.book_adapter import ROOT, find_book


class BookAdapterTests(unittest.TestCase):
    def test_real_book_and_absent_title(self):
        image = ROOT / "captures/20260922_195224_frame.png"
        result = find_book("岩石力学数值计算方法", image)
        self.assertTrue(result["found"])
        self.assertTrue(any("岩石力学" in r["text"] for r in result["matches"]))
        for item in result["matches"]:
            self.assertTrue(all(0 <= value <= 1 for value in item["normalized_center"]))
        self.assertFalse(result["indicator_lit"])
        self.assertFalse(result["source"]["live"])
        self.assertEqual(result["source"]["freshness"], "unknown")
        absent = find_book("ZXQ999完全不存在的火星植物百科", image, threshold=0.95)
        self.assertFalse(absent["found"])
        self.assertEqual(absent["matches"], [])

    def test_missing_invalid_input_and_timeout(self):
        with self.assertRaisesRegex(ValueError, "image_not_found"):
            find_book("书", ROOT / "does-not-exist.png")
        with self.assertRaisesRegex(ValueError, "invalid_book_title"):
            find_book(" ", "unused")
        with tempfile.TemporaryDirectory() as folder:
            invalid = Path(folder) / "broken.png"
            invalid.write_bytes(b"this is not an image")
            with self.assertRaisesRegex(ValueError, "book_scan_failed"):
                find_book("书", invalid)
        with self.assertRaisesRegex(ValueError, "book_scan_timeout"):
            find_book("书", ROOT / "captures/20260922_195224_frame.png", timeout_seconds=0.001)


if __name__ == "__main__":
    unittest.main()
