"""Simple-mode polling DMA with bounded reset/start waits.

Kept separate from the installed PYNQ driver. A timeout cannot recover a stuck
AXI bus read; hardware bus-response failures still require board recovery.
"""
import time


class BoundedDMA:
    def __init__(self, mmio, timeout=2.0, max_bytes=(1 << 23)-1):
        if not 0 < timeout < float('inf') or not 1 <= max_bytes <= (1 << 23)-1:
            raise ValueError('Invalid DMA limits')
        self.mmio, self.timeout, self.max_bytes = mmio, timeout, max_bytes
        self.failed = False
        self.sendchannel = _Channel(self, 0, True)
        self.recvchannel = _Channel(self, 0x30, False)
        try:
            mmio.write(0, 4)
            self.wait(lambda: not mmio.read(0) & 4, 'DMA reset')
            for offset in (0, 0x30):
                mmio.write(offset+4, 0x7000)  # Clear only write-one IRQ flags.
                mmio.write(offset, 1)
                self.wait(lambda offset=offset: not mmio.read(offset+4) & 1,
                          'DMA channel start')
        except Exception:
            self.failed = True
            raise

    def wait(self, predicate, label):
        deadline = time.monotonic()+self.timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise TimeoutError(label)
            time.sleep(.0001)


class _Channel:
    def __init__(self, owner, offset, send):
        self.owner, self.offset, self.send = owner, offset, send
        self.buffer = None

    @property
    def idle(self):
        status = self.owner.mmio.read(self.offset+4)
        if status & 0x770:
            self.owner.failed = True
            raise RuntimeError('AXI DMA error: 0x%x' % status)
        return bool(status & 2)

    def transfer(self, buffer):
        owner, offset = self.owner, self.offset
        if owner.failed:
            raise RuntimeError('Reset overlay after DMA failure')
        count, address = int(buffer.nbytes), int(buffer.physical_address)
        if not 1 <= count <= owner.max_bytes or not 0 <= address < (1 << 32):
            raise ValueError('Invalid DMA buffer length/address')
        if self.buffer is not None and not self.idle:
            raise RuntimeError('DMA channel still owns previous buffer')
        if owner.mmio.read(offset+4) & 0x771:
            owner.failed = True
            raise RuntimeError('DMA channel halted or in error')
        if self.send:
            buffer.flush()
        self.buffer = buffer  # Keep referenced until overlay reset or replacement.
        try:
            owner.mmio.write(offset+0x18, address)
            owner.mmio.write(offset+0x1c, 0)
            owner.mmio.write(offset+0x28, count)
        except Exception:
            owner.failed = True
            raise
