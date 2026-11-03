"""S3 native USB transport for the existing DeskService, with reconnect proof."""
import argparse
import json
import time
import uuid
from .pynq_service import (DeskService, FrameDecoder, encode, add_book_arguments,
                           configured_book_adapter)


def log(event, **data):
    print(json.dumps(dict(event=event, **data), ensure_ascii=True), flush=True)


def open_native_usb(serial_module, port):
    # Set ESP USB Serial/JTAG reset/boot control lines before opening.
    stream = serial_module.Serial(None, 115200, timeout=.1,
                                  write_timeout=1, exclusive=True)
    stream.dtr = False
    stream.rts = False
    stream.port = port
    stream.open()
    return stream


class USBSession:
    def __init__(self, service, send):
        self.decoder = FrameDecoder(service)
        self.send = send
        self.buffer = bytearray()
        self.overflow = False
        self.hello_id = uuid.uuid4().hex
        self.probe_id = None
        self.result_id = None
        self.confirmed = False

    def hello(self):
        self.send(encode(dict(v=1, type='hello', id=self.hello_id)))

    def feed(self, data):
        for byte in data:
            if byte != 10:
                if len(self.buffer) < 2049:
                    self.buffer.append(byte)
                else:
                    self.overflow = True
                continue
            line = bytes(self.buffer).rstrip(b'\r')
            self.buffer.clear()
            overflow, self.overflow = self.overflow, False
            # ROM boot logs may precede the app. Never answer non-JSON logs.
            if overflow or not line.startswith(b'{'):
                continue
            try:
                msg = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get('v') == 1 and msg.get('type') == 'hello':
                if msg.get('id') == self.hello_id:
                    log('usb_hello_received', transport=msg.get('transport'))
                elif (self.probe_id and msg.get('id') == self.probe_id
                      and msg.get('last_result_id') == self.result_id
                      and msg.get('last_result_status') == 'success'):
                    self.confirmed = True
                    log('usb_roundtrip_confirmed', request_id=self.result_id)
                continue
            for reply in self.decoder.feed(line + b'\n'):
                self.send(encode(reply))
                log('usb_reply', request_id=reply.get('id'), status=reply.get('status'),
                    action=msg.get('action'),error=reply.get('error'),
                    book_params=msg.get('params') if msg.get('action')=='book.find' else None)
                if msg.get('action') == 'protocol.info' and reply.get('status') == 'success':
                    self.result_id = reply['id']
                    self.probe_id = uuid.uuid4().hex
                    # FIFO ordering ensures S3 handles the result before this probe.
                    self.send(encode(dict(v=1, type='hello', id=self.probe_id, probe=True)))


def main():
    import serial
    from serial.tools import list_ports
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Default: uniquely discover Espressif 303a:1001')
    parser.add_argument('--db-path', default='output/usb-desk.sqlite3')
    parser.add_argument('--simulate', action='store_true')
    parser.add_argument('--posture-port',type=int,help='Loopback-only live detector ingress, e.g. 8767')
    parser.add_argument('--posture-runtime',help='Existing live pose directory for saved baseline/status/manual calibration')
    parser.add_argument('--posture-runner',help='Local trusted pose runner; never supplied by client commands')
    parser.add_argument('--paper-sorter',action='store_true',help='Enable integrated paper workflow; motor movement still requires explicit manual reference confirmation')
    parser.add_argument('--paper-motion',action='store_true',help='Explicitly permit motor commands; disabled for software integration')
    parser.add_argument('--paper-camera',default='1',help='Same physical camera as posture detector, used exclusively during paper capture')
    parser.add_argument('--lcd',action='store_true',help='Integrated LCD dashboard sharing the existing LED bridge')
    parser.add_argument('--lcd-python',action='store_true',help='Explicit slow fallback without native LCD library')
    parser.add_argument('--shelf-calibration', help='Enable confirmed OCR plus measured LED2 indication')
    parser.add_argument('--shelf-control-root', default='/home/xilinx/amd_lcd_burst_20261027')
    parser.add_argument('--shelf-snapshot-url', default='http://127.0.0.1:8766/snapshot')
    add_book_arguments(parser)
    args = parser.parse_args()
    if args.shelf_calibration:
        if args.simulate or args.book_image or args.book_camera is not None:
            parser.error('shelf mode requires the live snapshot daemon, without simulation or another source')
        if not args.book_ocr_server or not args.book_ocr_token_file:
            parser.error('shelf mode requires the PC server and private token file')
        import sys
        sys.path.append(args.shelf_control_root)
        from .shelf_book_adapter import board_adapter
        remote=board_adapter(args.book_ocr_server,args.book_ocr_token_file,args.shelf_calibration,
                             args.shelf_control_root,args.book_ocr_output,args.shelf_snapshot_url)
        log('shelf_backend_ready',calibration=args.shelf_calibration)
    else:
        remote = configured_book_adapter(args, parser)
    from .posture_control import PostureControl
    from .device_health import DeviceHealth
    service = DeskService(args.simulate, book_image=args.book_image,
                          db_path=args.db_path, book_adapter=remote,
                          posture_control=PostureControl(args.posture_runtime,runner=args.posture_runner,paper_camera=args.paper_camera) if args.posture_runtime else None,
                          health=DeviceHealth(args.book_ocr_server,args.book_ocr_token_file,args.shelf_snapshot_url) if args.shelf_calibration else None)
    ingress=None
    service.features.transition_reminders=True  # One reminder per observed good-to-bad transition.
    service.features.duration=0.0  # Live device: react to the first valid abnormal frame.
    images=None
    if service.posture_control is not None:
        from .posture_images import PostureImages
        try:
            images=PostureImages(service.posture_control).start()
            service.posture_control.images=images
        except OSError as error:log('posture_images_unavailable',reason=str(error))
    if args.paper_sorter:
        if remote is None or service.posture_control is None or not hasattr(remote,'lights'):
            parser.error('paper sorter requires existing shared bridge and posture camera owner')
        from .paper_adapter import create_paper_workflow
        service.paper_adapter=create_paper_workflow(remote.lights.bridge,service.posture_control,args.book_ocr_server,args.book_ocr_token_file,args.posture_runtime,allow_motion=args.paper_motion)
        log('paper_workflow_ready',hardware_available=service.paper_adapter.motors.available())
    previous_posture=None
    lcd=None;next_lcd=0
    if args.lcd:
        try:
            from adapter_control.dashboard_runtime import LCDDashboard,lcd_snapshot
            lcd=LCDDashboard(service.book_adapter.lights.bridge,args.posture_runtime,native=not args.lcd_python).start()
            log('lcd_dashboard_started')
        except (AttributeError,OSError,ValueError) as error:log('lcd_dashboard_unavailable',reason=str(error))
    def display_tick(connected):
        nonlocal next_lcd
        if lcd is not None:
            lcd.drain(service)
            if time.monotonic()>=next_lcd:
                lcd.publish(lcd_snapshot(service,connected));next_lcd=time.monotonic()+.5
    if service.posture_control is not None:
        try:
            log('posture_autostart',**service.posture_control.start())
        except (OSError,ValueError) as error:
            log('posture_autostart_failed',reason=str(error))
    if args.posture_port is not None:
        from .posture_ingress import PostureIngress
        ingress=PostureIngress(args.posture_port).start()
        log('posture_ingress_ready',port=ingress.port)
    try:
        while True:
            try:
                if ingress is not None:ingress.drain(service)
                service.collect_jobs()
                service.update_posture_light()
                display_tick(False)
                ports = [p.device for p in list_ports.comports()
                         if p.vid == 0x303a and p.pid == 0x1001]
                if not args.port and len(ports) != 1:
                    raise OSError('expected one S3 native USB port')
                port = args.port or ports[0]
                with open_native_usb(serial, port) as stream:
                    log('usb_connected', port=port)
                    def send(payload):
                        if stream.write(payload) != len(payload):
                            raise OSError('partial USB write')
                    session = USBSession(service, send)
                    session.hello()
                    deadline = time.monotonic() + 20
                    while True:
                        session.feed(stream.read(256))
                        if ingress is not None:
                            for update in ingress.drain(service):
                                state=update.get('classification')
                                if state!=previous_posture or update.get('reminded') or update.get('error'):
                                    log('posture_sample_processed',**update)
                                previous_posture=state
                        for event in service.poll_events():
                            send(encode(event))
                            if event.get('type')=='result':
                                log('usb_job_result',request_id=event.get('id'),status=event.get('status'),
                                    error=event.get('error'),found=event.get('data',{}).get('found'),
                                    indicator_lit=event.get('data',{}).get('indicator_lit'))
                            elif event.get('type')=='event':
                                log('usb_event_sent',name=event.get('name'),event_id=event.get('event_id'))
                        if not session.confirmed and time.monotonic() > deadline:
                            raise OSError('USB handshake timed out')
                        display_tick(session.confirmed)
            except (OSError, serial.SerialException) as error:
                log('usb_reconnect', reason=str(error))
                time.sleep(2)
    finally:
        if lcd is not None:lcd.close()
        if images is not None:images.close()
        if ingress is not None:ingress.close()
        service.close()


if __name__ == '__main__':
    main()
