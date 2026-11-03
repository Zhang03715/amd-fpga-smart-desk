"""Host side of the 50 MHz adapter command bridge and AXI UART Lite."""
import threading
import time


class Bridge:
    def __init__(self, gpio, clock=time.monotonic, timeout=1):
        self.mmio = gpio.mmio
        self.clock, self.timeout = clock, timeout
        self.lock = threading.RLock()
        self.toggle = self.mmio.read(8) & 1
        if self.mmio.read(8) >> 16 != 0x5a32:
            raise RuntimeError('Wrong overlay: adapter signature missing')
        self.mmio.write(4, 0)  # channel 1 output
        self.mmio.write(12, 0xffffffff)  # channel 2 input

    def status(self):
        return self.mmio.read(8)

    def command(self, opcode, value=0):
        if not 0 <= opcode < 128 or not 0 <= value < (1 << 24):
            raise ValueError('command_out_of_range')
        with self.lock:
            deadline = self.clock() + self.timeout
            while self.status() & 2:
                if self.clock() >= deadline:
                    raise TimeoutError('adapter_busy')
                time.sleep(0)
            self.toggle ^= 1
            self.mmio.write(0, self.toggle << 31 | opcode << 24 | value)
            while self.status() & 1 != self.toggle or self.status() & 2:
                if self.clock() >= deadline:
                    raise TimeoutError('adapter_command_timeout')
                time.sleep(0)

    def buttons(self):
        # bit order UP, DOWN, OK, BACK; 1 means pressed after PL debounce.
        with self.lock:return (self.status() >> 4) & 15


class UARTLite:
    def __init__(self, ip):
        self.mmio = ip.mmio
        self.mmio.write(12, 3)  # reset RX/TX FIFOs

    def read(self, limit=256):
        data = bytearray()
        while len(data) < limit:
            status = self.mmio.read(8)
            if status & 0xe0:
                self.mmio.write(12, 2)  # RX reset; bit 0 resets TX, preserve queued replies.
                raise IOError('UART RX overrun/parity/framing error')
            if not status & 1:
                break
            data.append(self.mmio.read(0) & 255)
        return bytes(data)

    def write(self, data, timeout=1):
        for byte in data:
            deadline = time.monotonic() + timeout
            while self.mmio.read(8) & 8:
                if time.monotonic() >= deadline:
                    raise TimeoutError('uart_tx_full')
                time.sleep(0)
            self.mmio.write(4, byte)


class Lights:
    def __init__(self, bridge):
        self.bridge = bridge

    def show(self, channel, pixels, brightness=0.1):
        pixels = list(pixels)
        if channel not in (0, 1) or not 1 <= len(pixels) <= 256:
            raise ValueError('channel_or_pixel_count')
        if not 0 <= brightness <= 1:
            raise ValueError('brightness')
        for rgb in pixels:
            if len(rgb) != 3 or any(type(x) is not int or not 0 <= x <= 255 for x in rgb):
                raise ValueError('invalid_rgb')
        # Hold the lock for the complete write/flush; do not mix frame buffers.
        with self.bridge.lock:
            for index, rgb in enumerate(pixels):
                if len(rgb) != 3 or any(type(x) is not int or not 0 <= x <= 255 for x in rgb):
                    raise ValueError('invalid_rgb')
                red, green, blue = (round(x * brightness) for x in rgb)
                self.bridge.command(0x10, channel << 8 | index)
                self.bridge.command(0x11, green << 16 | red << 8 | blue)
            self.bridge.command(0x12, channel << 9 | len(pixels))


class Motors:
    """Bench pulse control only, without position feedback/homing."""
    def __init__(self, bridge, allow=False):
        self.bridge, self.allow = bridge, allow

    def stop(self):
        self.bridge.command(0x3f)

    def keepalive(self):
        self.bridge.command(0x3e)

    def move(self, channel, steps, frequency=100, direction=0):
        if not self.allow:
            raise RuntimeError('motor control requires explicit opt-in')
        if channel not in range(4) or type(steps) is not int or not 1 <= steps <= 65535:
            raise ValueError('channel_or_steps')
        if not 50 <= frequency <= 5000 or direction not in (0, 1):
            raise ValueError('frequency_or_direction')
        with self.bridge.lock:
            self.bridge.command(0x31, round(50_000_000 / frequency) << 2 | channel)
            self.keepalive()
            self.bridge.command(0x30, steps << 3 | direction << 2 | channel)


def load(bitfile):
    from pynq import Overlay
    overlay = Overlay(bitfile)
    for name in ('adapter_bus', 's3_uart'):
        if name not in overlay.ip_dict:
            raise RuntimeError('Missing overlay IP: ' + name)
    return overlay, Bridge(overlay.adapter_bus), UARTLite(overlay.s3_uart)
