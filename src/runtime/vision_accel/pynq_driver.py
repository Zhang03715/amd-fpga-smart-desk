"""Experimental controlled-top driver. Importable on PC; hardware supplied by caller.

No overlay is loaded implicitly. A timeout/error requires resetting the overlay
and constructing a fresh driver: the RTL has no software error-reset command.
"""
import time
import numpy as np
from .packets import activation_packet, weight_packet, unpack_results


class VisionAccelerator:
    def __init__(self, mmio, dma, allocate, timeout=5.0):
        if not np.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be finite and positive')
        self.mmio, self.dma, self.allocate = mmio, dma, allocate
        self.timeout = timeout
        self.channels = None
        self.mask = 0
        self.failed = False

    def _wait(self, predicate, label):
        deadline = time.monotonic() + self.timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise TimeoutError(label)
            time.sleep(0.0001)

    def configure(self, weights, biases, multipliers, shifts, lane_mask=255):
        if self.failed:
            raise RuntimeError('Reset overlay after previous hardware failure')
        payload = weight_packet(weights)
        if type(lane_mask) is not int or not 0 <= lane_mask <= 255:
            raise ValueError('Invalid lane mask')
        arrays = []
        for values, lo, hi in [(biases, -(1<<31), (1<<31)-1),
                               (multipliers, 0, (1<<31)-1), (shifts, 0, 62)]:
            values = np.asarray(values)
            if values.shape != (8,) or values.dtype.kind not in 'iu' or any(
                    not lo <= int(v) <= hi for v in values):
                raise ValueError('Invalid eight-lane quantization configuration')
            arrays.append(values)
        bound = np.abs(np.asarray(weights).astype(np.int64)).sum(axis=1)*128
        bound += np.abs(arrays[0].astype(np.int64))
        if np.any(bound > (1<<31)-1):
            raise OverflowError('Potential int32 accumulator overflow')
        # A timeout during load must not leave a usable stale channel count.
        self.channels = None
        try:
            if self.mmio.read(4) & 0x16:  # loading, busy, frame_error
                raise RuntimeError('Accelerator is not available for configuration')
            self.mmio.write(8, len(payload)//8)
            self.mmio.write(12, lane_mask)
            for base, values in zip((0x100, 0x140, 0x180), arrays):
                for lane, value in enumerate(values):
                    self.mmio.write(base+4*lane, int(value) & 0xffffffff)
            self.mmio.write(0, 1)
            self._wait(lambda: bool(self.mmio.read(4) & 2), 'weight load start')
            for offset in range(0, len(payload), 8):
                word = int.from_bytes(payload[offset:offset+8], 'little')
                self.mmio.write(0x20, word & 0xffffffff)
                self.mmio.write(0x24, word >> 32)
                self.mmio.write(0x28, 1)
            self._wait(lambda: self.mmio.read(4) & 0x33 == 0x21, 'weights ready')
            self.channels, self.mask = len(payload)//8, lane_mask
        except Exception:
            self.failed = True
            raise

    def run(self, activation):
        packet = activation_packet(activation)
        if self.failed or self.channels != len(packet):
            raise RuntimeError('Configure matching weights on a healthy overlay first')
        source = self.allocate(shape=(len(packet),), dtype=np.uint8)
        result = None
        try:
            result = self.allocate(shape=(8,), dtype=np.int32)
            source[:] = np.frombuffer(packet, dtype=np.uint8)
            # Receive must be armed before the accelerator can emit any results.
            self.dma.recvchannel.transfer(result)
            self.mmio.write(0, 2)
            self.dma.sendchannel.transfer(source)
            def completed():
                if self.mmio.read(4) & 16:
                    raise RuntimeError('Malformed activation AXIS frame')
                for offset in (0x04, 0x34):
                    if self.dma.mmio.read(offset) & 0x770:
                        raise RuntimeError('AXI DMA error')
                return self.dma.sendchannel.idle and self.dma.recvchannel.idle
            self._wait(completed, 'DMA transaction')
            result.invalidate()
            self._wait(lambda: bool(self.mmio.read(4) & 8), 'accelerator completion')
            return unpack_results(result.tobytes(), self.mask)
        except Exception:
            self.failed = True
            # Buffers can still be owned by DMA. Keep them alive until caller
            # resets the overlay; freeing active DMA memory is unsafe.
            self._failed_buffers = (source, result)
            raise
        finally:
            if not self.failed:
                source.freebuffer()
                if result is not None:
                    result.freebuffer()
