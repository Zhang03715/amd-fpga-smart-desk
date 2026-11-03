import unittest
from .bounded_dma import BoundedDMA


class Registers:
    def __init__(self, stuck=False):
        self.values = {4: 1, 0x34: 1}
        self.writes = []
        self.stuck = stuck
    def read(self, address):return self.values.get(address, 0)
    def write(self, address, value):
        self.writes.append((address,value))
        if address == 0 and value == 4:
            self.values[0] = 4 if self.stuck else 0
        elif address in (0,0x30) and value == 1:
            self.values[address+4] = 2


class Buffer:
    nbytes = 3
    physical_address = 0x1000000
    def __init__(self):self.flushed = False
    def flush(self):self.flushed = True


class BoundedDMATests(unittest.TestCase):
    def test_stuck_reset_times_out(self):
        with self.assertRaisesRegex(TimeoutError,'reset'):
            BoundedDMA(Registers(True),timeout=.001)

    def test_start_address_length_and_cache_order(self):
        r=Registers();dma=BoundedDMA(r);b=Buffer()
        dma.sendchannel.transfer(b)
        self.assertTrue(b.flushed)
        self.assertEqual(r.writes[-3:],[(0x18,b.physical_address),(0x1c,0),(0x28,3)])
        b=Buffer();dma.recvchannel.transfer(b)
        self.assertFalse(b.flushed)
        self.assertEqual(r.writes[-3:],[(0x48,b.physical_address),(0x4c,0),(0x58,3)])

    def test_invalid_buffer_and_errors(self):
        r=Registers();dma=BoundedDMA(r);b=Buffer();b.nbytes=0
        with self.assertRaises(ValueError):dma.sendchannel.transfer(b)
        b.nbytes=1;b.physical_address=1 << 32
        with self.assertRaises(ValueError):dma.sendchannel.transfer(b)
        r.values[4]=0x10
        with self.assertRaisesRegex(RuntimeError,'DMA error'):_=dma.sendchannel.idle
        with self.assertRaisesRegex(RuntimeError,'failure'):dma.recvchannel.transfer(Buffer())
