"""PYNQ UART service. Default mode refuses physical actions; --simulate is explicit."""
import argparse
from collections import OrderedDict, deque
from datetime import datetime, timezone, timedelta
import json
import sys
import time
import math
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
try:
    from .book_adapter import find_book
    from .desk_features import FeatureService
except ImportError:
    from book_adapter import find_book
    from desk_features import FeatureService

MAX_FRAME = 2048

def compact_book_evidence(evidence):
    """Whitelist evidence for UART; complete local/remote reports stay on disk."""
    if not isinstance(evidence, dict) or not isinstance(evidence.get('matches'), list):
        raise ValueError('book_result_invalid')
    matches = evidence['matches']
    source = evidence.get('source', {})
    data = {key: evidence[key] for key in ('found', 'indicator_lit', 'motor_action', 'shelf_slot') if key in evidence}
    for key, allowed in [('horizontal_physical',range(31,45)),('vertical_physical',range(22,31))]:
        if key in evidence:
            values=evidence[key]
            if not isinstance(values,list) or len(values)>len(allowed) or any(type(v) is not int or v not in allowed for v in values):
                raise ValueError('book_result_invalid')
            data[key]=values
    if 'geometry_status' in evidence:data['geometry_status']=str(evidence['geometry_status'])[:64]
    data.update(title=str(evidence.get('title', ''))[:200], match_count=len(matches),
                source={key: source[key] for key in ('kind', 'live', 'freshness', 'clock', 'age_at_result_seconds') if key in source})
    if 'spine_count' in evidence:
        if type(evidence['spine_count']) is not int or not 0 <= evidence['spine_count'] <= len(matches):
            raise ValueError('book_result_invalid')
        data.update(spine_count=evidence['spine_count'],spine_count_semantics='OCR_anchored_spine_hypotheses')
    if evidence.get('geometry_quality_evaluated') is True:
        review_count=evidence.get('geometry_review_required_count')
        if (type(review_count) is not int or 'spine_count' not in data
                or not 0<=review_count<=data['spine_count']):
            raise ValueError('book_result_invalid')
        data.update(geometry_quality_evaluated=True,geometry_review_required_count=review_count)
    for key, limit in (('capture_id', 64), ('captured_at', 80), ('capture_time', 80)):
        if key in source:
            data['source'][key] = source[key][:limit] if isinstance(source[key], str) else None
    if isinstance(source.get('camera_id'),str):data['source']['camera_id']=source['camera_id'][:64]
    if 'image_size' in evidence:
        size=evidence['image_size']
        if not isinstance(size,list) or len(size)!=2 or any(type(v) is not int or not 1<=v<=10000 for v in size):
            raise ValueError('book_result_invalid')
        data['image_size']=size
    for key, limit in (('remote_request_id', 64), ('image_sha256', 64), ('inference_location', 32), ('message', 100),
                       ('requested_title',100),('query_normalization',64)):
        if key in evidence:
            data[key] = str(evidence[key])[:limit]
    data['matches'] = [{key: match[key][:96] if key == 'text' else match[key]
                        for key in ('text', 'match_score', 'book_box', 'normalized_center') if key in match}
                       for match in matches[:2]]
    data['matches_truncated'] = len(matches) > len(data['matches']) or any(len(m.get('text', '')) > 96 for m in matches[:2])
    # Leave room for both result and job.get envelopes, including Unicode IDs.
    size = lambda: len(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'))
    if size() > 1200:
        data.pop('message', None)
        data['title'] = data['title'][:64]
    while data['matches'] and size() > 1200:
        data['matches'].pop()
        data['matches_truncated'] = True
    if size() > 1200:
        data['source'] = {key: data['source'][key] for key in ('kind', 'live', 'freshness') if key in data['source']}
    if size() > 1200:
        raise ValueError('book_result_invalid')
    return data


class DeskService:
    def __init__(self, simulate=False, clock=time.monotonic, book_image=None, db_path=':memory:', book_adapter=None, posture_control=None, health=None, paper_adapter=None):
        self.paper_adapter=paper_adapter
        self.health=health
        self.posture_light_active = False
        self.posture_light_error = None
        self.posture_auto_resume = posture_control is not None
        self.posture_resume_pending = False
        self.posture_resume_error = None
        self.posture_control = posture_control
        self.simulate = simulate
        self.clock = clock
        self.cache = OrderedDict()
        self.timer_end = None
        self.timer_remaining = None
        self.timer_phase = 'focus'
        self.timer_work_seconds = 1500
        self.timer_total = 1500
        self.timer_cycle = 1
        self.focus_light_signature = None
        self.book_light_until = 0
        self.book_image = book_image
        self.book_adapter = book_adapter
        self.features = FeatureService(db_path=db_path, clock=clock,
                                       now=lambda: datetime.now(timezone(timedelta(hours=8))))
        self.light_state = {'scene': 'off', 'brightness': 0, 'rgb': [0, 0, 0], 'applied': False}
        self.jobs = OrderedDict()
        self.completed = deque(maxlen=32)
        self.event_session=uuid.uuid4().hex[:16]
        self.event_sequence=0
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='book-ocr')

    def close(self):
        if self.health is not None:self.health.close()
        self.worker.shutdown(wait=True, cancel_futures=True)
        if self.paper_adapter is not None:self.paper_adapter.close()
        self.features.close()

    def collect_jobs(self):
        for rid, job in self.jobs.items():
            future = job.get('future')
            if future is None or not future.done():
                continue
            try:
                evidence = future.result()
                # Return compact evidence within the UART frame budget; full OCR is local.
                result = self.result(rid, 'success', data=evidence if job.get('kind') in ('calibration','paper') else compact_book_evidence(evidence))
            except Exception as exc:
                result = self.result(rid, 'failed', error=str(exc) if isinstance(exc, ValueError) else 'paper_classification_failed' if job.get('kind')=='paper' else 'book_scan_failed')
                messages={'ocr_service_unreachable':'电脑端OCR服务连接失败，请检查服务和热点连接。',
                          'ocr_processing_timeout':'电脑端OCR处理超时，本次未完成识别，请稍后重试。'}
                if result['error'] in messages:result['message']=messages[result['error']]
            job['result'] = result
            job['future'] = None
            self.focus_light_signature = None
            if job.get('kind') not in ('calibration','paper'):
                self.book_light_until = float('inf') if result.get('status')=='success' and result.get('data',{}).get('indicator_lit') else 0
            elif job.get('kind')=='calibration':self.book_light_until=0
            if rid in self.cache:
                self.cache[rid] = (self.cache[rid][0], result)
            self.completed.append(result)
        if self.posture_resume_pending and not any(job['future'] is not None for job in self.jobs.values()):
            self.posture_resume_pending = False
            if self.posture_auto_resume and self.posture_control is not None:
                try:
                    self.posture_control.start()
                    self.posture_resume_error = None
                except (OSError, ValueError) as exc:
                    self.posture_resume_error = str(exc)

    def run_shelf_job(self, function, *args):
        if self.posture_control is not None:
            self.posture_control.prepare_shelf()
        return function(*args)

    def handle(self, request):
        self.collect_jobs()
        if not isinstance(request, dict) or type(request.get('v')) is not int or request.get('v') != 1 or request.get('type') != 'request':
            raise ValueError('invalid_envelope')
        rid = request.get('id')
        if not isinstance(rid, str) or not 1 <= len(rid) <= 64:
            raise ValueError('invalid_id')
        fingerprint = json.dumps(request, sort_keys=True, ensure_ascii=False)
        if rid in self.cache:
            old, result = self.cache[rid]
            if old == fingerprint:
                return result
            return self.result(rid, 'failed', error='id_conflict')
        action, params = request.get('action'), request.get('params')
        try:
            if not isinstance(params, dict):
                raise ValueError('invalid_params')
            if action=='paper.classify':
                if params.get('operation')=='full_cycle':
                    if set(params)-{'operation','count'} or type(params.get('count',1)) is not int or not 1<=params.get('count',1)<=100:raise ValueError('invalid_paper_parameters')
                elif params not in ({},{'operation':'wrong_question'}):raise ValueError('invalid_paper_parameters')
                if self.paper_adapter is None:raise ValueError('paper_service_not_configured')
                if any(job['future'] is not None for job in self.jobs.values()):raise ValueError('paper_busy')
                if len(self.jobs)>=32:
                    finished=next((key for key,job in self.jobs.items() if job['future'] is None),None)
                    if finished:self.jobs.pop(finished)
                result=self.result(rid,'pending',data=dict(state='classifying'))
                self.jobs[rid]=dict(future=self.worker.submit((lambda: self.paper_adapter.run_full_cycle(params.get('count',1))) if params.get('operation')=='full_cycle' else self.paper_adapter.capture_wrong_question if params.get('operation')=='wrong_question' else self.paper_adapter.classify),result=result,kind='paper')
            elif action=='light.calibration' and hasattr(self.book_adapter,'calibrate'):

                mode=params.get('mode','start')
                if mode=='status':
                    result=self.result(rid,'success',data=self.book_adapter.calibration_info())
                elif mode=='start':
                    if self.paper_adapter and self.paper_adapter.status().get('sheet',{}):
                        sheet=self.paper_adapter.status().get('sheet')
                        if sheet and sheet['state'] not in ('motion_complete','interrupted'):raise ValueError('paper_busy')
                    if any(job['future'] is not None for job in self.jobs.values()):raise ValueError('book_scan_busy')
                    if len(self.jobs)>=32:
                        finished=next((key for key,job in self.jobs.items() if job['future'] is None),None)
                        if finished:self.jobs.pop(finished)
                    result=self.result(rid,'pending',data=dict(request_id=rid,state='calibrating',completed=False,
                                       message='正在逐颗标定，请保持摄像头和灯带不动，约需90秒；等待最终结果。'))
                    future=self.worker.submit(self.run_shelf_job,self.book_adapter.calibrate)
                    self.posture_resume_pending = True
                    self.jobs[rid]=dict(future=future,result=result,kind='calibration')
                else:raise ValueError('invalid_calibration_mode')
            elif action == 'book.find' and (self.book_image or self.book_adapter is not None):
                if self.paper_adapter:
                    sheet=self.paper_adapter.status().get('sheet')
                    if sheet and sheet['state'] not in ('motion_complete','interrupted'):raise ValueError('paper_busy')
                title = params.get('title',params.get('book_name'))
                if 'title' in params and 'book_name' in params and params['title']!=params['book_name']:
                    raise ValueError('conflicting_book_title')
                if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
                    raise ValueError('title_required')
                if sum(job['future'] is not None for job in self.jobs.values()) >= getattr(self.book_adapter,'max_pending_jobs',2):
                    raise ValueError('book_scan_busy')
                if len(self.jobs) >= 32:
                    finished = next((key for key, job in self.jobs.items() if job['future'] is None), None)
                    if finished: self.jobs.pop(finished)
                source_kind = ('camera_snapshot' if getattr(self.book_adapter, 'camera', None) is not None else 'offline_image')
                result = self.result(rid, 'pending', data={'request_id': rid, 'source_kind': source_kind})
                future = (self.worker.submit(self.run_shelf_job, self.book_adapter.find, title, self.book_image, rid)
                          if self.book_adapter is not None else self.worker.submit(find_book, title, self.book_image))
                self.jobs[rid] = {'future': future, 'result': result, 'title':title}
                self.posture_resume_pending = True
            else:
                data = self.execute(action, params)
                result = self.result(rid, 'success', data=data)
        except ValueError as exc:
            result = self.result(rid, 'failed', error=str(exc))
        except OSError:
            result = self.result(rid, 'failed', error='device_io_unavailable')
        except sqlite3.Error:
            result = self.result(rid, 'failed', error='storage_unavailable')
        self.cache[rid] = (fingerprint, result)
        while len(self.cache) > 128:
            self.cache.popitem(last=False)
        return result

    @staticmethod
    def result(rid, status, **fields):
        return dict(v=1, type='result', id=rid, status=status, **fields)

    def execute(self, action, params):
        if action=='paper.status':
            return self.paper_adapter.status() if self.paper_adapter else dict(motor=dict(available=False,state='unavailable',reason='paper_service_not_configured'),sheet=None,classifying=False)
        if action in ('paper.home','paper.feed','paper.dispatch','paper.stop','paper.release'):
            if self.paper_adapter is None:raise ValueError('paper_service_not_configured')
            if action=='paper.stop':return self.paper_adapter.stop()
            if action=='paper.release':return self.paper_adapter.stop(release=True)
            return getattr(self.paper_adapter,action.split('.')[1])(params)
        if action=='status' and params.get('details') is True:
            return dict(health=self.health.snapshot() if self.health is not None else {'checking':False,'configured':False},
                        detector=self.posture_control.status() if self.posture_control is not None else None,
                        timer=self.timer_status(),active_jobs=sum(job['future'] is not None for job in self.jobs.values()))
        if action == 'posture.config' and params.get('operation') == 'camera':
            if self.paper_adapter and self.paper_adapter.classifying:raise ValueError('paper_busy')
            if self.posture_control is None:raise ValueError('posture_control_not_configured')
            if any(job['future'] is not None for job in self.jobs.values()):raise ValueError('book_scan_busy')
            mode=params.get('mode')
            result=self.posture_control.switch(mode)
            if mode in ('off','posture'):self.posture_auto_resume = mode == 'posture'
            return result
        if action == 'posture.start' or action == 'posture.config' and params.get('operation') == 'start':
            if any(job['future'] is not None for job in self.jobs.values()):raise ValueError('book_scan_busy')
            if self.posture_control is None:raise ValueError('posture_control_not_configured')
            result=self.posture_control.start()
            self.posture_auto_resume = True
            return result
        if action == 'posture.calibrate':
            if self.posture_control is None:raise ValueError('posture_control_not_configured')
            return self.posture_control.calibrate()
        if action == 'posture.status' and self.posture_control is not None:
            status=self.features.execute(action,params)
            return dict(status,detector=self.posture_control.status(),
                        abnormal_seconds=round(max(0,self.clock()-self.features.bad_since),1) if not status['stale'] and self.features.bad_since is not None else 0,
                        alert_after_seconds=self.features.duration,
                        red_light_active=self.posture_light_active,red_light_error=self.posture_light_error)
        if action == 'protocol.info':
            return dict(name='amd-desk-uart',version=1,baud=115200,framing='UTF-8 JSON LF',
                        max_payload_bytes=MAX_FRAME,request_id_dedup=True,
                        ack_timeout_seconds=2,max_same_id_retries=2,book_timeout_seconds=95,
                        capabilities=['book.find','job.get','timer','light.scene','posture.status'])
        if action == 'status':
            return dict(mode='simulation' if self.simulate else 'safe', timer_active=self.timer_end is not None and self.clock() < self.timer_end,
                        hardware_ready=False, timer=self.timer_status(), light=self.light_state,
                        book_source=('camera_snapshot' if getattr(self.book_adapter, 'camera', None) is not None
                                     else 'offline_image' if self.book_image else 'not_connected'),
                        book_backend='remote_pc' if self.book_adapter is not None else 'local')
        if action == 'timer.status':
            return self.timer_status()
        if action == 'timer.pause':
            if self.timer_end is None or self.clock() >= self.timer_end:
                raise ValueError('timer_not_running')
            self.timer_remaining = self.timer_end - self.clock()
            self.timer_end = None
            return self.timer_status()
        if action == 'timer.resume':
            if self.timer_remaining is None:
                raise ValueError('timer_not_paused')
            self.timer_end = self.clock() + self.timer_remaining
            self.timer_remaining = None
            return self.timer_status()
        if action == 'job.get':
            rid = params.get('request_id')
            if not isinstance(rid, str) or rid not in self.jobs:
                raise ValueError('job_not_found')
            return self.jobs[rid]['result']
        if action == 'timer.start':
            minutes = params.get('minutes', 25)
            if type(minutes) is not int or not 1 <= minutes <= 120:
                raise ValueError('minutes_must_be_1_to_120')
            self.book_light_until=0
            self.timer_phase = 'focus'
            self.timer_work_seconds = minutes * 60
            self.timer_total = minutes * 60
            self.timer_cycle = 1
            self.timer_end = self.clock() + minutes * 60
            self.timer_remaining = None
            return dict(minutes=minutes)
        if action == 'timer.stop':
            self.timer_end = None
            self.timer_remaining = None
            return dict(timer_active=False)
        if action == 'light.scene':
            if params.get('scene') not in ('focus', 'rest', 'off'):
                raise ValueError('invalid_scene')
            brightness = params.get('brightness', 50)
            if type(brightness) is not int or not 0 <= brightness <= 100:
                raise ValueError('invalid_brightness')
            if params['scene']=='off' and self.book_adapter is not None and hasattr(self.book_adapter,'clear'):
                if any(job['future'] is not None for job in self.jobs.values()):raise ValueError('book_scan_busy')
                self.book_adapter.clear();self.book_light_until=0
                self.book_adapter.indication_pixels=None
                self.focus_light_signature=None
                return dict(scene='off',applied=True)
            if self.simulate:
                # Future light adapter applies validated state only after hardware feedback.
                rgb = params.get('rgb', [255, 220, 180] if params['scene'] == 'focus' else [255, 160, 80])
                if not isinstance(rgb, list) or len(rgb) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in rgb):
                    raise ValueError('invalid_rgb')
                if params['scene'] == 'off': brightness, rgb = 0, [0, 0, 0]
                self.light_state = dict(scene=params['scene'], brightness=brightness, rgb=rgb, applied=False)
                return dict(simulated=True, **self.light_state)
            raise ValueError('light_driver_not_connected')
        if action == 'book.find':
            if not isinstance(params.get('title'), str) or not params['title'].strip():
                raise ValueError('title_required')
            raise ValueError('camera_and_locator_not_connected')
        if action == 'paper.file':
            # TODO: after mechanics/limits are confirmed, add a separate physical filing adapter.
            # Metadata CRUD below does not move paper or drive any motor.
            raise ValueError('mechanical_driver_not_connected')
        if action in self.features.ACTIONS:
            return self.features.execute(action, params)
        raise ValueError('unknown_action')

    def timer_status(self):
        remaining = self.timer_remaining if self.timer_remaining is not None else max(0, self.timer_end - self.clock()) if self.timer_end is not None else 0
        state = 'paused' if self.timer_remaining is not None else 'running' if remaining > 0 else 'idle'
        return dict(state=state, remaining_seconds=math.ceil(remaining), phase=self.timer_phase,
                    total_seconds=self.timer_total, cycle=self.timer_cycle, auto_repeat=True, rest_seconds=300)

    def update_posture_light(self):
        """Only the USB owner writes posture lights; book workers take priority."""
        adapter = self.book_adapter
        if adapter is None or not hasattr(adapter, 'posture_alert'):
            return
        if any(job['future'] is not None for job in self.jobs.values()):
            self.posture_light_active = False
            return
        status = self.features.execute('posture.status', {})
        mode = self.posture_control.status().get('camera_mode') if self.posture_control else 'posture'
        wanted = (mode == 'posture' and not status['stale'] and
                  status['classification'] == 'bad' and self.features.bad_since is not None and
                  self.clock() - self.features.bad_since >= self.features.duration)
        if not wanted and hasattr(adapter, 'focus_countdown'):
            if self.posture_light_active:
                self.focus_light_signature = None
            if self.clock() < self.book_light_until:
                if self.posture_light_active and hasattr(adapter,'restore_indication'):
                    adapter.restore_indication()
                self.posture_light_active=False
                return
            from adapter_control.focus_lights import plan
            pixels, count = plan(self.timer_status())
            signature = (self.timer_phase, count)
            try:
                if signature != self.focus_light_signature:
                    adapter.focus_countdown(pixels)
                    self.focus_light_signature = signature
                self.posture_light_active = False
                self.posture_light_error = None
            except (OSError, ValueError, RuntimeError) as exc:
                self.posture_light_error = str(exc)
            return
        if wanted == self.posture_light_active:
            return
        try:
            adapter.posture_alert(wanted)
            self.focus_light_signature = None
            self.posture_light_active = wanted
            self.posture_light_error = None
        except (OSError, ValueError, RuntimeError) as exc:
            self.posture_light_error = str(exc)

    def poll_events(self):
        self.collect_jobs()
        if self.posture_control is not None and getattr(self.posture_control,'images',None) is not None:
            snapshot=self.execute('posture.status',{})
            snapshot.pop('detector',None)
            self.posture_control.images.alert=dict(snapshot,updated_monotonic=time.monotonic())
        events = list(self.completed)
        self.completed.clear()
        events.extend(self.features.poll_events())
        if self.timer_end is not None and self.clock() >= self.timer_end:
            finished = self.timer_phase
            # Advance from the original deadline, so polling delays do not accumulate.
            while self.clock() >= self.timer_end:
                self.timer_phase = 'rest' if self.timer_phase == 'focus' else 'focus'
                if self.timer_phase == 'focus': self.timer_cycle += 1
                self.timer_total = 300 if self.timer_phase == 'rest' else self.timer_work_seconds
                self.timer_end += self.timer_total
            events.append(dict(v=1, type='event', name='timer.finished',
                               data=dict(finished_phase=finished, next_phase=self.timer_phase, auto_repeat=True)))
        self.update_posture_light()
        for event in events:
            if event.get('type')=='event' and 'event_id' not in event:
                self.event_sequence+=1
                event['event_id']=f'{self.event_session}-{self.event_sequence}'
        return events

def encode(message):
    payload = json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(payload) > MAX_FRAME:
        # Never emit a frame S3 cannot receive. A response-size failure does not undo a write.
        fallback = dict(v=1, type='result' if 'id' in message else 'error',
                        error='response_too_large', execution_unknown=True)
        if 'id' in message: fallback.update(id=message['id'], status='failed')
        payload = json.dumps(fallback, separators=(',', ':')).encode('utf-8')
    return payload + b'\n'


def error_message(error):
    return dict(v=1, type='error', error=error)


def decode_frame(service, frame):
    def reject_constant(value):
        raise ValueError('invalid_json')

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result

    try:
        request = json.loads(frame.decode('utf-8'), parse_constant=reject_constant,
                             object_pairs_hook=unique_object)
        return service.handle(request)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return error_message('invalid_json')
    except ValueError as exc:
        return error_message(str(exc))


class FrameDecoder:
    """Bounded UTF-8 JSON lines: 2048 payload bytes, excluding LF/optional CR."""
    def __init__(self, service):
        self.service = service
        self.buffer = bytearray()
        self.overflow = False

    def feed(self, data):
        replies = []
        for byte in data:
            if byte == 10:
                if self.overflow:
                    replies.append(error_message('frame_too_large'))
                elif self.buffer:
                    frame = self.buffer[:-1] if self.buffer[-1] == 13 else self.buffer
                    if len(frame) > MAX_FRAME:
                        replies.append(error_message('frame_too_large'))
                    elif frame:
                        replies.append(decode_frame(self.service, frame))
                self.buffer.clear()
                self.overflow = False
            elif not self.overflow:
                if len(self.buffer) < MAX_FRAME + 1:
                    self.buffer.append(byte)
                else:
                    self.buffer.clear()
                    self.overflow = True
        return replies

def add_book_arguments(parser):
    """Shared opt-in configuration for UART service and adapter menu entrypoints."""
    parser.add_argument('--book-image', help='Explicit offline image; never presented as a live camera')
    parser.add_argument('--book-ocr-server', help='Opt-in PC OCR HTTP origin, e.g. http://192.0.2.10:8787')
    parser.add_argument('--book-ocr-token-file', help='Private token file; Linux permissions 600')
    parser.add_argument('--book-camera', help='Remote OCR only: capture camera index or /dev/videoN per request')
    parser.add_argument('--book-camera-runtime-path', help='Existing isolated OpenCV runtime directory')
    parser.add_argument('--book-ocr-output', default='output/remote-book', help='Full remote OCR reports on this board')
    parser.add_argument('--book-ocr-timeout', type=float, default=180)


def configured_book_adapter(args, parser):
    remote = None
    if bool(args.book_ocr_server) != bool(args.book_ocr_token_file):
        parser.error('--book-ocr-server and --book-ocr-token-file must be supplied together')
    if args.book_camera is not None and (not args.book_ocr_server or args.book_image):
        parser.error('--book-camera requires remote OCR and cannot be combined with --book-image')
    if args.book_ocr_server:
        if not args.book_image and args.book_camera is None:
            parser.error('remote OCR requires --book-image or --book-camera')
        try:
            try:
                from .remote_book_adapter import RemoteBookAdapter
            except ImportError:
                from remote_book_adapter import RemoteBookAdapter
            remote = RemoteBookAdapter(args.book_ocr_server, args.book_ocr_token_file,
                                       camera=args.book_camera, runtime_path=args.book_camera_runtime_path,
                                       output_root=args.book_ocr_output, total_timeout=args.book_ocr_timeout)
        except (ValueError, OSError, RuntimeError) as exc:
            parser.error('remote OCR configuration failed: ' + str(exc))
    return remote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', help='PYNQ UART device or Windows USB UART COM port')
    parser.add_argument('--simulate', action='store_true')
    parser.add_argument('--posture-port', type=int, help='Optional loopback detector HTTP port, e.g. 8766')
    add_book_arguments(parser)
    parser.add_argument('--db-path', default='desk_records.sqlite3')
    args = parser.parse_args()
    remote = configured_book_adapter(args, parser)
    service = DeskService(args.simulate, book_image=args.book_image, db_path=args.db_path, book_adapter=remote)
    decoder = FrameDecoder(service)
    ingress = None
    if args.posture_port is not None:
        try:
            from .posture_ingress import PostureIngress
        except ImportError:
            from posture_ingress import PostureIngress
        ingress = PostureIngress(args.posture_port).start()
    if not args.port and ingress is not None:
        # Headless detector validation: same service owns samples and events.
        try:
            while True:
                ingress.drain(service)
                for event in service.poll_events():
                    sys.stdout.buffer.write(encode(event))
                sys.stdout.buffer.flush()
                time.sleep(0.05)
        except KeyboardInterrupt:
            return
        finally:
            ingress.close()
            service.close()
    if not args.port:
        # stdin is a line-oriented protocol demonstration, not a live timer daemon.
        while True:
            chunk = sys.stdin.buffer.read1(256)
            if not chunk:
                break
            for reply in decoder.feed(chunk):
                sys.stdout.buffer.write(encode(reply))
            sys.stdout.buffer.flush()
        return
    try:
        import serial
        with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as uart:
            while True:
                if ingress is not None:
                    ingress.drain(service)
                for reply in decoder.feed(uart.read(256)):
                    uart.write(encode(reply))
                for event in service.poll_events(): uart.write(encode(event))
    finally:
        if ingress is not None:
            ingress.close()
        service.close()

if __name__ == '__main__': main()
