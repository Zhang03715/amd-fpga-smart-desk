"""Single-thread LCD/button/camera bring-up, without S3 UART polling.

Camera worker continuously captures the latest frame; LCD refresh is limited.
Attach to an already validated adapter overlay without reconfiguring the FPGA.
"""
import argparse
from collections import deque
import time
import signal
from PIL import Image
from .hardware import Bridge
from .lcd import ST7789
from .menu import Menu, Buttons
from .run import AdapterService
from .camera_preview import LatestCamera


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bitfile', required=True)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--posture-status', help='Optional upper-body diagnostic status JSON')
    parser.add_argument('--native-lcd', action='store_true')
    parser.add_argument('--require-lcd-burst', action='store_true',
                        help='Refuse an overlay without three-byte LCD capability')
    parser.add_argument('--start-camera', action='store_true')
    parser.add_argument('--preview-fps', type=float, default=1.0,
                        help='Target LCD update rate (1..10); actual rate is measured, not guaranteed')
    parser.add_argument('--inversion', choices=('on', 'off'),
                        help='Explicit LCD inversion override, applied by the sole display owner')
    parser.add_argument('--initialize', action='store_true',
                        help='Load the adapter overlay and initialize LCD after board reboot')
    args = parser.parse_args()
    if not 1 <= args.preview_fps <= 10:
        parser.error('--preview-fps must be within 1..10')
    from pynq import Overlay
    overlay = Overlay(args.bitfile, download=args.initialize)
    bridge = Bridge(overlay.adapter_bus)
    capability = bridge.status()
    print('LCD_CAPABILITIES', hex(capability), flush=True)
    if args.require_lcd_burst and not capability & 0x1000:
        raise RuntimeError('Overlay lacks three-byte LCD capability')
    if args.native_lcd:
        from .native_lcd import enable
        enable(bridge)
    lcd = ST7789(bridge)
    if args.initialize:
        lcd.initialize()
    if args.inversion is not None:
        lcd.command(0x21 if args.inversion == 'on' else 0x20)
        print('LCD_INVERSION', args.inversion, flush=True)
    service = AdapterService(simulate=False)
    menu = Menu(service, '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    buttons = Buttons()
    pending_keys = deque(maxlen=64)
    def sample_buttons():
        pending_keys.extend(buttons.update(bridge.buttons()))
    # Preserve short presses while native batches are transferring a frame.
    # All MMIO access remains on this owner thread.
    lcd.pump = sample_buttons
    camera = None
    next_capture = 0
    last_sequence = None
    if args.start_camera:
        menu.page = 'camera'
    dirty = True
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    print('LCD_ONLY_MENU_START', flush=True)
    try:
        while True:
            sample_buttons()
            while pending_keys:
                key = pending_keys.popleft()
                menu.key(key)
                dirty = True
            if menu.page == 'camera':
                if camera is None:
                    camera = LatestCamera(args.camera)
                    next_capture = 0
                    last_sequence = None
                if time.monotonic() >= next_capture:
                    next_capture = time.monotonic()+1.0/args.preview_fps
                    try:
                        frame, sequence, age = camera.latest()
                        if sequence != last_sequence:
                            menu.camera = frame
                            menu.camera_source = 'USB live / latest frame'
                            if args.posture_status:
                                from .posture_display import posture_label
                                menu.camera_source = posture_label(args.posture_status, time.monotonic())
                            last_sequence = sequence
                            dirty = True
                            print('CAMERA_FRAME', sequence, 'age_seconds', round(age, 3), flush=True)
                    except (OSError, ValueError, RuntimeError):
                        menu.camera = None
                        menu.camera_source = 'Camera unavailable / waiting'
                        dirty = True
            elif camera is not None:
                try:
                    camera.close()
                finally:
                    camera = None
                    menu.camera = None
                    print('CAMERA_CLOSED', flush=True)
            if dirty:
                started = time.monotonic()
                count = lcd.show(menu.render())
                print('FRAME_COMPLETE', count, time.monotonic()-started,
                      'at', round(time.monotonic(), 3), flush=True)
                dirty = False
            time.sleep(.02)
    finally:
        if camera is not None:
            camera.close()
        service.close()


if __name__ == '__main__': main()
