import unittest
import numpy as np
from .asymmetric import prepare_accumulation


class AsymmetricTests(unittest.TestCase):
    def test_accumulators_equal_direct_zero_point_subtraction(self):
        rng = np.random.default_rng(20261019)
        for channels in (1, 3, 16, 240, 480):
            x = rng.integers(0, 256, (5, channels), dtype=np.uint8)
            x[0, :] = 0
            x[1, :] = 255
            w = rng.integers(-128, 128, (8, channels), dtype=np.int8)
            w[0, :] = -128
            bias = rng.integers(-10000, 10001, 8, dtype=np.int32)
            for zero in (0, 9, 128, 255):
                signed, converted = prepare_accumulation(x, w, bias, zero)
                expected = (x.astype(np.int64)-zero)@w.astype(np.int64).T+bias
                actual = signed.astype(np.int64)@w.astype(np.int64).T+converted
                np.testing.assert_array_equal(actual, expected)
                self.assertEqual(signed.dtype, np.int8)
                self.assertEqual(converted.dtype, np.int32)

    def test_conversion_overflow_is_rejected(self):
        with self.assertRaises(OverflowError):
            prepare_accumulation(np.zeros((1, 480), np.uint8),
                                 np.full((8, 480), -128, np.int8),
                                 np.full(8, -(1<<31), np.int32), 0)

    def test_input_type_and_zero_point_are_checked(self):
        for zero in (-1, 256, 9.0):
            with self.assertRaises(ValueError):
                prepare_accumulation(np.zeros((1, 1), np.uint8),
                                     np.zeros((8, 1), np.int8),
                                     np.zeros(8, np.int32), zero)


if __name__ == '__main__': unittest.main()
