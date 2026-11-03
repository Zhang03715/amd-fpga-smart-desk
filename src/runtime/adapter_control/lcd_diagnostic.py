"""LCD-only staged board probe: no UART, camera, service or worker threads."""
import argparse
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bitfile', required=True)
    parser.add_argument('--log', required=True)
    args = parser.parse_args()
    log = Path(args.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def stage(name, **details):
        line = json.dumps(dict(stage=name, elapsed=time.monotonic()-started, **details))
        print(line, flush=True)
        with log.open('a', encoding='utf-8') as stream:
            stream.write(line+'\n')
            stream.flush()

    stage('import_pynq')
    from pynq import Overlay
    from PIL import Image
    from .hardware import Bridge
    from .lcd import ST7789
    stage('load_overlay')
    overlay = Overlay(args.bitfile)
    stage('overlay_loaded')
    # Do not instantiate UARTLite: isolate all access to the LCD command bridge.
    bridge = Bridge(overlay.adapter_bus)
    stage('bridge_ready', status=hex(bridge.status()))
    lcd = ST7789(bridge)
    lcd.initialize()
    stage('lcd_initialized')
    # Write short stripes with explicit boundaries. Sleep between stripes lets
    # the operator distinguish slow pixel progress from complete system stalls.
    for y in range(0, 320, 8):
        lcd.window((0, y, 240, min(y+8, 320)))
        color = b'\xf8\x00' if y < 160 else b'\x00\x1f'
        lcd.data(color*240*min(8, 320-y))
        stage('stripe_complete', y=y, bytes=240*min(8, 320-y)*2)
        time.sleep(.02)
    stage('frame_complete')
    # Leave the image visible; no automatic reload, reset or second owner.


if __name__ == '__main__':
    main()
