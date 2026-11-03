"""One owner for menu, timer, UART protocol and hardware state."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time
import threading
import sys
from PIL import Image
from voice_bridge.pynq_service import (DeskService, FrameDecoder, encode,
                                      add_book_arguments, configured_book_adapter)
from .hardware import load, Lights, Motors
from .lcd import Panel, ST7789, PreviewLCD
from .menu import Menu, Buttons
from .transport import UARTTransport


class AdapterService(DeskService):
    def __init__(self, lights=None, counts=(1, 1), active_counts=None, active_masks=None, spine_mapper=None, **kwargs):
        super().__init__(**kwargs)
        self.lights, self.counts = lights, counts
        self.active_counts = tuple(active_counts) if active_counts is not None else counts
        if len(self.active_counts)!=2 or any(type(a) is not int or not 0<=a<=n for a,n in zip(self.active_counts,counts)):
            raise ValueError('invalid_active_led_counts')
        self.active_masks=tuple(tuple(range(a)) for a in self.active_counts) if active_masks is None else tuple(tuple(m) for m in active_masks)
        if len(self.active_masks)!=2 or any(len(set(mask))!=len(mask) or any(type(i) is not int or not 0<=i<n for i in mask)
                                          for mask,n in zip(self.active_masks,counts)):
            raise ValueError('invalid_active_led_mask')
        self.active_counts=tuple(len(mask) for mask in self.active_masks)
        self.spine_mapper = spine_mapper
        self.book_view = dict(state='idle', request_id=None, title='', indicator_lit=False)
        self.book_view_started = None

    def _clear_book_indicator(self):
        if self.book_view.get('indicator_lit') and self.lights is not None:
            try:self.lights.show(1,[(0,0,0)]*self.counts[1],brightness=0)
            except Exception:self.book_view['hardware_state_unknown']=True
        self.book_view['indicator_lit']=False

    def handle(self, request):
        # A retry may return an old job; only a newly accepted request owns the display.
        rid = request.get('id') if isinstance(request, dict) else None
        is_new = isinstance(rid, str) and rid not in self.cache and rid not in self.jobs
        response = super().handle(request)
        if (isinstance(request, dict) and request.get('action') == 'book.find'
                and is_new and response.get('status') == 'pending'
                and request.get('id') != self.book_view.get('request_id')):
            self._clear_book_indicator()
            self.book_view = dict(state='searching', request_id=request['id'],
                                  title=request['params']['title'], indicator_lit=False)
            self.book_view_started = self.clock()
        elif (isinstance(request, dict) and request.get('action') == 'book.find'
              and is_new and response.get('status') == 'failed' and request.get('id') not in self.jobs):
            self.book_view = dict(state='failed',request_id=request.get('id'),title='',
                                  error=response.get('error'),indicator_lit=False)
        self.update_book_view()
        return response

    def update_book_view(self):
        rid = self.book_view.get('request_id')
        if (self.book_view.get('state') in ('found','not_found')
                and self.clock()-self.book_view.get('completed_at',self.clock())>=30):
            self._clear_book_indicator()
            self.book_view.update(state='expired',result={},indicator_lit=False,guidance='none')
        if self.book_view.get('state') != 'searching' or rid not in self.jobs:
            return
        if self.clock() - self.book_view_started >= 90:
            self.book_view.update(state='timeout', error='result_unknown', indicator_lit=False)
            return
        result = self.jobs[rid]['result']
        if result['status'] != 'pending':
            data = result.get('data', {})
            self.book_view.update(state=('failed' if result['status'] != 'success' else
                                         'found' if data.get('found') else 'not_found'),
                                  result=deepcopy(data), error=result.get('error'), indicator_lit=False,
                                  completed_at=self.clock(),
                                  guidance='calibration_required' if data.get('found') else 'none')

    def collect_jobs(self):
        super().collect_jobs()
        if hasattr(self, 'book_view'):
            self.update_book_view()

    def execute(self, action, params):
        if action == 'light.calibration':
            from .led2_layout import Led2Layout
            return self.spine_mapper.info() if self.spine_mapper else dict(configured=False,layout=Led2Layout.info())
        if action == 'book.indicate':
            self.update_book_view()
            view=self.book_view
            if not self.spine_mapper or self.lights is None:raise ValueError('light_calibration_required')
            if view['state']!='found' or params.get('request_id')!=view['request_id']:
                raise ValueError('book_result_not_current')
            data=view['result'];source=data.get('source',{})
            age=source.get('age_at_result_seconds')
            import math
            if (source.get('live') is not True or source.get('kind')!='camera'
                    or type(age) not in (int,float) or not math.isfinite(age) or age<0
                    or age+self.clock()-view['completed_at']>30):raise ValueError('book_snapshot_not_fresh')
            matches=data.get('matches',[])
            if data.get('matches_truncated') or (len(matches)!=1 and 'match_index' not in params):
                raise ValueError('book_match_selection_required')
            index=params.get('match_index',0)
            if type(index) is not int or not 0<=index<len(matches):raise ValueError('invalid_match_index')
            if data.get('geometry_quality_evaluated') is not True or data.get('geometry_review_required_count')!=0:
                raise ValueError('book_geometry_unverified')
            match=matches[index]
            try:
                indices=self.spine_mapper.plan(match['book_box'],camera_id=source['camera_id'],
                    image_size=data['image_size'],target_id=(view['request_id'],index))
            except (KeyError,TypeError):raise ValueError('book_geometry_missing')
            if (self.counts[1]!=self.spine_mapper.physical_count
                    or not set(self.spine_mapper.pixel_indices)<=set(self.active_masks[1])):
                raise ValueError('light_profile_mismatch')
            try:self.lights.show(1,self.spine_mapper.pixels(indices),brightness=.08)
            except Exception:
                view.update(indicator_lit=False,guidance='hardware_state_unknown')
                raise ValueError('indicator_write_failed')
            view.update(indicator_lit=True,guidance='led2',led_indices=indices)
            return dict(indicator_lit=True,led_indices=indices,index_base=0,channel=1,
                        physical_count=self.counts[1],active_count=self.active_counts[1],feedback='fpga_frame_completed',
                        calibration_id=self.spine_mapper.calibration_id)
        if action == 'book.status':
            self.collect_jobs()
            return deepcopy(self.book_view)
        if action == 'book.cancel':
            # Cancel presentation; a running OCR worker may still finish on disk.
            rid = self.book_view.get('request_id')
            if rid in self.jobs and self.jobs[rid].get('future') is not None:
                self.jobs[rid]['future'].cancel()
            self._clear_book_indicator()
            self.book_view = dict(state='cancelled', request_id=rid, title=self.book_view.get('title',''),
                                  indicator_lit=False, worker_may_still_finish=True)
            return deepcopy(self.book_view)
        if action == 'light.scene' and self.lights is not None:
            # Reuse existing validation on THIS service instance. No second timer
            # or FeatureService is created. Roll back state on transport failure.
            old_mode, old_state = self.simulate, self.light_state.copy()
            try:
                self.simulate = True
                result = super().execute(action, params)
            finally:
                self.simulate = old_mode
            try:
                for channel, count in enumerate(self.counts):
                    self.lights.show(channel, [tuple(result['rgb']) if i in self.active_masks[channel] else (0,0,0) for i in range(count)],
                                     result['brightness'] / 100)
                self.light_state['applied'] = True
                self.book_view.update(indicator_lit=False,guidance='manual_light_scene')
                return dict(simulated=False, **self.light_state)
            except Exception:
                # Some channels may have changed; do not claim atomic execution.
                self.light_state = dict(old_state, applied=False, hardware_state='unknown', error='light_transfer_failed')
                raise ValueError('light_transfer_failed')
        return super().execute(action, params)


class Camera:
    """Background latest-frame preview. Time is host read completion, not sensor time."""
    def __init__(self, index, max_age=2.0, capture=None, cv2module=None, clock=time.monotonic):
        if cv2module is None:
            import cv2 as cv2module
        self.cv2, self.clock, self.max_age = cv2module, clock, max_age
        self.capture = capture if capture is not None else self.cv2.VideoCapture(index)
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError('camera_open_failed')
        self.capture.set(self.cv2.CAP_PROP_FRAME_WIDTH, 320)
        self.capture.set(self.cv2.CAP_PROP_FRAME_HEIGHT, 240)
        self.capture.set(self.cv2.CAP_PROP_BUFFERSIZE, 1)
        self.lock = threading.Lock()
        self.latest, self.captured_at = None, None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._capture, daemon=True, name='adapter-camera')
        self.thread.start()

    def _capture(self):
        while not self.stopped.is_set():
            try:
                ok, frame = self.capture.read()
                image = Image.fromarray(self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)) if ok else None
            except Exception:
                image = None
            with self.lock:
                self.latest = image
                self.captured_at = self.clock() if image is not None else None
            if image is None:
                self.stopped.wait(0.02)

    def read(self):
        with self.lock:
            if self.latest is None or self.captured_at is None:
                return None
            if not 0 <= self.clock() - self.captured_at <= self.max_age:
                return None
            return self.latest.copy()

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=0.2)
        # A hung backend may not react to stop. Avoid concurrent release/read;
        # its daemon thread is abandoned on process exit and reported.
        if self.thread.is_alive():
            print('camera backend read did not stop; restart process before reopening', file=sys.stderr)
        else:
            self.capture.release()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--bitfile', help='matching adapter.bit and adapter.hwh')
    parser.add_argument('--preview', default='output/adapter-menu.png')
    parser.add_argument('--image', help='static preview image; not OCR or a live camera')
    parser.add_argument('--camera', type=int)
    parser.add_argument('--font', help='optional .ttf/.ttc file for Chinese text')
    parser.add_argument('--panel-config', help='JSON Panel fields including MADCTL and offsets')
    parser.add_argument('--keys', default='', help='desktop scripted keys: down,ok,back,...')
    parser.add_argument('--db-path', default=':memory:')
    parser.add_argument('--led-counts', default='1,1', help='actual strip lengths, max 256 each')
    parser.add_argument('--once', action='store_true')
    add_book_arguments(parser)
    args = parser.parse_args(argv)
    # Validate remote configuration before touching any PL or UART resource.
    remote_book = configured_book_adapter(args, parser)
    if args.camera is not None and args.book_camera is not None:
        preview_device = str(args.camera)
        book_device = str(args.book_camera)
        if book_device.startswith('/dev/video'):
            book_device = book_device[len('/dev/video'):]
        if book_device == preview_device:
            parser.error('preview and OCR must not open the same camera concurrently; select separate USB devices')
    panel = Panel(**json.loads(Path(args.panel_config).read_text(encoding='utf-8'))) if args.panel_config else Panel()
    counts = tuple(int(x) for x in args.led_counts.split(','))
    if len(counts) != 2 or any(not 1 <= x <= 256 for x in counts):
        parser.error('--led-counts requires two integers from 1 to 256')
    if args.keys and args.bitfile:
        parser.error('--keys is for desktop preview only')
    Path(args.preview).parent.mkdir(parents=True, exist_ok=True)
    bridge = uart = camera = motors = transport = None
    service = None
    old_switch_interval = sys.getswitchinterval()
    try:
        if args.bitfile:
            _, bridge, uart = load(args.bitfile)
            # Best effort only: a 16-byte FIFO at 115200 fills in ~1.39 ms.
            sys.setswitchinterval(min(old_switch_interval, 0.0005))
            transport = UARTTransport(uart).start()
            motors = Motors(bridge)  # not enabled by this application
            motors.stop()
            lights = Lights(bridge)
            # Send complete off frames, not just a reset, for the configured length.
            for channel, count in enumerate(counts): lights.show(channel, [(0, 0, 0)] * count)
        else: lights = None
        service = AdapterService(lights=lights, counts=counts, simulate=False,
                                 db_path=args.db_path, book_image=args.book_image,
                                 book_adapter=remote_book)
        decoder = FrameDecoder(service)
        menu = Menu(service, args.font)
        def pump():
            if transport:
                for item in transport.poll():
                    if isinstance(item, Exception):
                        # Drop the damaged partial line until its next LF.
                        decoder.buffer.clear()
                        decoder.overflow = True
                        print(str(item), file=sys.stderr)
                    else:
                        for reply in decoder.feed(item): transport.write(encode(reply))
                for event in service.poll_events(): transport.write(encode(event))
        def serviced_sleep(seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                pump()
                time.sleep(min(0.001, max(0, deadline - time.monotonic())))
        lcd = ST7789(bridge, panel, pump=pump, sleep=serviced_sleep) if bridge else PreviewLCD(args.preview, panel)
        lcd.initialize()
        if args.image:
            with Image.open(args.image) as image: menu.camera = image.convert('RGB')
            menu.camera_source = 'Static image / not live'
        if args.camera is not None:
            camera = Camera(args.camera)
            menu.camera_source = 'USB preview / host timestamp'
        for key in filter(None, args.keys.split(',')):
            if key not in ('up', 'down', 'ok', 'back'): parser.error('invalid preview key')
            menu.key(key)
        buttons = Buttons()
        next_render = 0
        while True:
            pump()
            if bridge:
                for key in buttons.update(bridge.buttons()):
                    menu.key(key)
                    next_render = 0
            now = time.monotonic()
            if now >= next_render:
                if menu.page == 'camera' and camera: menu.camera = camera.read()
                lcd.show(menu.render((panel.width, panel.height)))
                # Schedule from completion: no catch-up loop after a slow transfer.
                next_render = time.monotonic() + 1
            if args.once or not bridge: break
            time.sleep(0.002)
        if not bridge: print('Desktop preview only: ' + str(Path(args.preview).resolve()))
    finally:
        sys.setswitchinterval(old_switch_interval)
        if motors:
            try: motors.stop()
            except Exception: pass  # PL watchdog also handles a dead host.
        if transport: transport.close()
        if camera: camera.close()
        if service: service.close()


if __name__ == '__main__':
    main()
