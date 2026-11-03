"""Host-side driver sequencing/failure tests; no claim of hardware validation."""
import unittest
import numpy as np
from .pynq_driver import VisionAccelerator


class Buffer(np.ndarray):
    def invalidate(self): self.events.append('invalidate')
    def freebuffer(self): self.events.append('free')


class DriverTests(unittest.TestCase):
    def setup_device(self, error=False):
        events = []
        class Registers:
            status = 0x21
            def read(self, offset): return self.status
            def write(self, offset, value):
                events.append((offset, value))
                if offset == 0: self.status = 2 if value == 1 else 0x29
                if offset == 0x28: self.status = 0x21
        class Channel:
            idle = True
            def __init__(self, name): self.name = name
            def transfer(self, buffer):
                events.append(self.name)
                if self.name == 'recv': buffer[:] = [4]*8
        class DMA:
            sendchannel = Channel('send')
            recvchannel = Channel('recv')
            class mmio:
                @staticmethod
                def read(offset): return 0x10 if error else 2
        def allocate(shape, dtype):
            buffer = np.zeros(shape, dtype=dtype).view(Buffer)
            buffer.events = events
            return buffer
        return VisionAccelerator(Registers(), DMA(), allocate), events

    def test_receive_before_start_and_signed_result(self):
        driver, events = self.setup_device()
        driver.configure(np.ones((8, 1), np.int8), np.zeros(8, np.int32),
                         np.ones(8, np.int32), np.zeros(8, np.int32))
        np.testing.assert_array_equal(driver.run(np.array([4], np.int8)), [4]*8)
        self.assertLess(events.index('recv'), events.index((0, 2)))
        self.assertLess(events.index((0, 2)), events.index('send'))
        self.assertEqual(events.count('free'), 2)
        self.assertIn('invalidate', events)

    def test_dma_error_retains_buffers_and_requires_reset(self):
        driver, events = self.setup_device(error=True)
        driver.channels = 1
        with self.assertRaisesRegex(RuntimeError, 'DMA error'):
            driver.run(np.array([1], np.int8))
        self.assertNotIn('free', events)
        self.assertEqual(len(driver._failed_buffers), 2)
        with self.assertRaisesRegex(RuntimeError, 'healthy overlay'):
            driver.run(np.array([1], np.int8))

    def test_invalid_quantization_causes_no_writes(self):
        driver, events = self.setup_device()
        with self.assertRaises(ValueError):
            driver.configure(np.ones((8, 1), np.int8), np.zeros(8, np.int32),
                             np.ones(8, np.int32), np.full(8, 63, np.int32))
        self.assertEqual(events, [])

    def test_accumulator_bound_rejected_before_configuration(self):
        driver, events = self.setup_device()
        with self.assertRaises(OverflowError):
            driver.configure(np.full((8, 480), -128, np.int8),
                             np.full(8, (1<<31)-1, np.int32),
                             np.ones(8, np.int32), np.zeros(8, np.int32))
        self.assertEqual(events, [])

    def test_dma_timeout_retains_buffers(self):
        driver, events = self.setup_device()
        driver.channels = 1
        driver.timeout = 0.001
        driver.dma.sendchannel.idle = False
        with self.assertRaises(TimeoutError):
            driver.run(np.array([1], np.int8))
        self.assertTrue(driver.failed)
        self.assertNotIn('free', events)


if __name__ == '__main__': unittest.main()
