import unittest
import threading
from unittest.mock import patch
from PIL import Image
from .lcd import Panel, ST7789, rgb565
from .menu import Buttons, Menu
from .hardware import Motors, Lights
from .run import AdapterService


class Recorder:
    def __init__(self):
        self.calls = []
        self.lock = threading.RLock()
    def command(self, op, value=0):
        self.calls.append((op, value))


class AdapterTests(unittest.TestCase):
    def test_native_lcd_batches_preserve_exact_byte_stream(self):
        class BatchBridge:
            def __init__(self): self.batches=[]
            def data_bytes(self, data): self.batches.append(bytes(data))
        bridge=BatchBridge()
        pumps=[]
        lcd=ST7789(bridge,pump=lambda:pumps.append(True))
        payload=bytes(range(256))*33
        lcd.data(payload)
        self.assertEqual(b''.join(bridge.batches),payload)
        self.assertEqual(list(map(len,bridge.batches)),[4096,4096,256])
        self.assertEqual(len(pumps),3)

    def test_menu_renders_with_board_pillow_font_api(self):
        from PIL import ImageFont
        fallback = ImageFont.load_default()
        service = AdapterService()
        try:
            with patch('adapter_control.menu.ImageFont.load_default',
                       side_effect=[TypeError('unexpected size'), fallback]) as loader:
                menu = Menu(service)
                self.assertEqual(menu.render().size, (240, 320))
                menu.render()
                self.assertEqual(loader.call_count, 2)
        finally:
            service.close()

    def test_rgb565_wire_order(self):
        im = Image.new('RGB', (3, 1)); im.putdata([(255,0,0),(0,255,0),(0,0,255)])
        self.assertEqual(rgb565(im), bytes.fromhex('f80007e0001f'))

    def test_panel_initialization_and_window(self):
        bridge = Recorder(); lcd = ST7789(bridge, Panel(x_offset=2, y_offset=3), sleep=lambda _:None)
        lcd.initialize()
        self.assertIn((1,0x11), bridge.calls)
        self.assertIn((1,0x3a), bridge.calls)
        self.assertIn((2,0x55), bridge.calls)
        bridge.calls.clear(); lcd.window((0,0,2,1))
        self.assertEqual(bridge.calls[:5], [(1,0x2a),(2,0),(2,2),(2,0),(2,3)])
        with self.assertRaises(ValueError): lcd.window((0,0,241,320))

    def test_dirty_rectangle_and_identical_frame(self):
        bridge=Recorder();lcd=ST7789(bridge,Panel(width=2,height=2))
        image=Image.new('RGB',(2,2),'black')
        self.assertEqual(lcd.show(image),8)
        bridge.calls.clear()
        self.assertEqual(lcd.show(image),0)
        self.assertEqual(bridge.calls,[])
        image.putpixel((1,1),(255,0,0))
        self.assertEqual(lcd.show(image),2)

    def test_press_edges_not_repeated_hold(self):
        b=Buttons()
        self.assertEqual(b.update(1),['up'])
        self.assertEqual(b.update(1),[])
        b.update(0)
        self.assertEqual(b.update(1),['up'])

    def test_menu_timer_reuses_service(self):
        clock=[100.0]
        service=AdapterService(clock=lambda:clock[0])
        try:
            menu=Menu(service);menu.key('down');menu.key('ok')
            self.assertEqual(service.timer_status()['remaining_seconds'],1500)
            clock[0]+=1501
            self.assertEqual(service.poll_events()[0]['name'],'timer.finished')
            menu.key('back');self.assertEqual(menu.page,'menu')
        finally:service.close()

    def test_grb_two_channels_and_bounds(self):
        bridge=Recorder();lights=Lights(bridge)
        lights.show(1,[(10,20,30)],1)
        self.assertEqual(bridge.calls,[(0x10,256),(0x11,0x140a1e),(0x12,513)])
        with self.assertRaises(ValueError):lights.show(0,[(0,0,0)]*257)

    def test_motor_opt_in_and_encoding(self):
        bridge=Recorder()
        with self.assertRaises(RuntimeError):Motors(bridge).move(0,10)
        self.assertEqual(bridge.calls,[])
        motor=Motors(bridge,allow=True);motor.move(2,10,100,1)
        self.assertEqual(bridge.calls[-1],(0x30,86))
        motor.stop();self.assertEqual(bridge.calls[-1],(0x3f,0))

    def test_light_failure_is_not_success(self):
        class Broken:
            def show(self,*args):raise IOError('not connected')
        service=AdapterService(lights=Broken())
        try:
            with self.assertRaises(ValueError):service.execute('light.scene',{'scene':'focus'})
            self.assertFalse(service.light_state['applied'])
            self.assertFalse(service.simulate)
        finally:service.close()


class TransportAndFreshnessTests(unittest.TestCase):
    def test_menu_and_uart_share_timer_and_light_failure_is_visible(self):
        import json
        from voice_bridge.pynq_service import FrameDecoder
        service = AdapterService()
        try:
            decoder = FrameDecoder(service)
            request = dict(v=1, type='request', id='timer', action='timer.start', params={'minutes': 2})
            reply = decoder.feed(json.dumps(request).encode() + b'\n')[0]
            self.assertEqual(reply['status'], 'success')
            menu = Menu(service)
            menu.key('down'); menu.key('ok')
            self.assertGreater(service.timer_status()['remaining_seconds'], 110)
            self.assertLessEqual(service.timer_status()['remaining_seconds'], 120)
            menu.key('back'); menu.key('down'); menu.key('down'); menu.key('ok')
            self.assertEqual(menu.page, 'lights')
            self.assertEqual(menu.message, 'light_driver_not_connected')
        finally:
            service.close()

    def test_uart_rx_error_reset_preserves_tx_fifo(self):
        from .hardware import UARTLite
        class MMIO:
            def __init__(self):
                self.rx = [123]
                self.tx = [77, 88]
                self.error = 0
                self.writes = []
            def read(self, address):
                if address == 8: return self.error
                raise AssertionError('unexpected read')
            def write(self, address, value):
                self.writes.append((address, value))
                if address == 12:
                    if value & 2: self.rx.clear()
                    if value & 1: self.tx.clear()
        class IP: pass
        ip = IP(); ip.mmio = MMIO()
        uart = UARTLite(ip)
        self.assertEqual(ip.mmio.writes, [(12, 3)])
        for status in (0x20, 0x40, 0x80):
            ip.mmio.rx = [123]; ip.mmio.tx = [77, 88]; ip.mmio.error = status
            with self.assertRaises(IOError): uart.read()
            self.assertEqual(ip.mmio.rx, [])
            self.assertEqual(ip.mmio.tx, [77, 88])
            self.assertEqual(ip.mmio.writes[-1], (12, 2))

    def test_lights_validate_entire_frame_before_mutating_hardware(self):
        bridge = Recorder()
        with self.assertRaises(ValueError):
            Lights(bridge).show(0, [(1, 2, 3), (0, 0, 999)])
        self.assertEqual(bridge.calls, [])

    def test_partial_channel_light_failure_marks_hardware_unknown(self):
        class Partial:
            def __init__(self): self.calls = 0
            def show(self, *args):
                self.calls += 1
                if self.calls == 2: raise IOError('second strip failed')
        lights = Partial()
        service = AdapterService(lights=lights)
        try:
            with self.assertRaisesRegex(ValueError, 'light_transfer_failed'):
                service.execute('light.scene', {'scene': 'focus'})
            self.assertEqual(lights.calls, 2)
            self.assertFalse(service.light_state['applied'])
            self.assertEqual(service.light_state['hardware_state'], 'unknown')
        finally: service.close()

    def test_rx_continues_while_tx_and_owner_are_blocked(self):
        from queue import Queue, Empty
        from .transport import UARTTransport
        class FakeUART:
            def __init__(self):
                self.rx = Queue()
                self.writing = threading.Event()
                self.release = threading.Event()
            def read(self):
                try: return self.rx.get_nowait()
                except Empty: return b''
            def write(self, data):
                self.writing.set()
                self.release.wait(1)
        uart = FakeUART()
        transport = UARTTransport(uart).start()
        try:
            transport.write(b'reply')
            self.assertTrue(uart.writing.wait(.5))
            # Owner is intentionally not pumping during the entire burst.
            chunks = [bytes([i]) * 16 for i in range(100)]
            for chunk in chunks: uart.rx.put(chunk)
            import time
            deadline = time.monotonic() + 1
            while not uart.rx.empty() and time.monotonic() < deadline: time.sleep(.001)
            self.assertTrue(uart.rx.empty())
            self.assertEqual(b''.join(transport.poll()), b''.join(chunks))
        finally:
            uart.release.set()
            transport.close()

    def test_rx_host_queue_overflow_is_explicit_and_bounded(self):
        from .transport import UARTTransport
        transport = UARTTransport(None, rx_limit=16)
        transport._append(b'1234567890')
        transport._append(b'1234567890')
        items = transport.poll()
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], IOError)
        self.assertEqual(transport.rx_size, 0)
        transport.close()

    def test_blocked_camera_does_not_block_ui_and_frame_expires(self):
        import time
        import numpy as np
        from .run import Camera
        class CV:
            CAP_PROP_FRAME_WIDTH=3; CAP_PROP_FRAME_HEIGHT=4; CAP_PROP_BUFFERSIZE=38
            COLOR_BGR2RGB=1
            @staticmethod
            def cvtColor(frame, _): return frame
        class Capture:
            def __init__(self):
                self.done = threading.Event(); self.release_read = threading.Event(); self.n = 0
            def isOpened(self): return True
            def set(self, *args): pass
            def read(self):
                self.n += 1
                if self.n == 1: return True, np.zeros((2, 2, 3), dtype=np.uint8)
                self.done.set()
                self.release_read.wait(1)
                return False, None
            def release(self): pass
        capture = Capture(); clock = [0]
        camera = Camera(0, capture=capture, cv2module=CV, clock=lambda: clock[0])
        try:
            self.assertTrue(capture.done.wait(.5))
            self.assertIsNotNone(camera.read())
            clock[0] = 3
            start = time.monotonic()
            self.assertIsNone(camera.read())
            self.assertLess(time.monotonic() - start, .1)
        finally:
            capture.release_read.set()
            camera.close()


if __name__ == '__main__':
    unittest.main()
