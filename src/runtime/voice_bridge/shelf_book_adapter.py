"""Confirmed camera OCR and measured LED indication, called by one DeskService worker."""
import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from ocr_link.client import make_request, NetworkError
from ocr_link.consensus import BookFrameConsensus,repeated_prefix_query
from adapter_control.local_book_lights import select_axis,horizontal_mapping
from .shelf_calibration import SHELF_LED_CHANNEL


class ShelfBookAdapter:
    camera = '0'
    max_pending_jobs = 1

    def __init__(self, client, lights, calibration, output_root, snapshot,
                 verify_anchors, clock=time.monotonic, calibrator=None, calibration_path=None):
        self.client, self.lights, self.snapshot = client, lights, snapshot
        self.verify_anchors, self.clock = verify_anchors, clock
        self.calibration = calibration
        self.calibrator=calibrator;self.calibration_path=Path(calibration_path) if calibration_path else None
        self.calibration_valid=not (self.calibration_path and self.calibration_path.with_suffix('.invalid').exists())
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.black = [(0, 0, 0)]*60
        self.indication_pixels = None
        for axis, allowed, minimum in [('horizontal', range(30,44),8), ('vertical',range(21,30),5)]:
            points = calibration.get(axis, [])
            if len(points)<minimum or len({p['index'] for p in points})!=len(points):
                raise ValueError('insufficient_calibration')
            if any(type(p['index']) is not int or p['index'] not in allowed for p in points):
                raise ValueError('invalid_calibration_indices')
            if any(len(p['xy'])!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p['xy'])
                   or not 0<=p['xy'][0]<1920 or not 0<=p['xy'][1]<1080 for p in points):
                raise ValueError('invalid_calibration_coordinates')
        if calibration.get('image_size') != [1920,1080]:
            raise ValueError('invalid_calibration_size')

    def clear(self):
        self.lights.show(SHELF_LED_CHANNEL,self.black,brightness=.10)

    def restore_indication(self):
        if self.indication_pixels is not None:
            self.lights.show(SHELF_LED_CHANNEL,self.indication_pixels,brightness=.10)

    def focus_countdown(self, pixels):
        self.lights.show(SHELF_LED_CHANNEL, pixels, brightness=.10)

    def posture_alert(self, active):
        # Fixed installed segments; calibration visibility must not hide a warning.
        pixels = list(self.black)
        if active:
            for index in range(21, 44):
                pixels[index] = (255, 0, 0)
        self.lights.show(SHELF_LED_CHANNEL, pixels, brightness=.10)

    def calibration_info(self):
        return dict(calibrated=self.calibration_valid,horizontal_count=len(self.calibration['horizontal']),
                    vertical_count=len(self.calibration['vertical']),
                    missing_physical=[i+1 for i in self.calibration.get('missing',[])],
                    calibration_action='light.calibration',start_params={'mode':'start'})

    def calibrate(self):
        if self.calibrator is None or self.calibration_path is None:raise ValueError('calibration_not_configured')
        self.indication_pixels=None
        self.calibration_valid=False
        invalid=self.calibration_path.with_suffix('.invalid');invalid.write_text('calibration in progress or failed')
        try:
            measured=self.calibrator(self.output_root/('calibration-'+uuid.uuid4().hex))
            temporary=self.calibration_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(measured,indent=2));temporary.replace(self.calibration_path)
            self.calibration=measured;invalid.unlink();self.calibration_valid=True
            return dict(completed=True,state='calibrated',**self.calibration_info(),
                        indicator_lit=False,message='灯带标定完成并保存，灯带已关闭。')
        finally:self.clear()

    def find(self, title, image_path=None, uart_request_id=None):
        if image_path or not isinstance(title,str) or not 1<=len(title.strip())<=200:
            raise ValueError('invalid_book_title_or_source')
        output = self.output_root/uuid.uuid4().hex
        output.mkdir()
        started = self.clock()
        try:
            self.indication_pixels=None
            self.clear()
            if not self.calibration_valid:raise ValueError('calibration_required')
            audit=self.verify_anchors(self.calibration)
            (output/'anchor-check.json').write_text(json.dumps(audit,indent=2))
            consensus = BookFrameConsensus(title,max_frames=1,single_frame=True)
            interpreted=repeated_prefix_query(title)
            alternative=BookFrameConsensus(interpreted,max_frames=1,single_frame=True) if interpreted else None
            alternative_match=None
            alternative_context=None
            match = None
            frame_seconds=0
            for attempt in range(1,2):
                if self.clock()-started>70:raise ValueError('book_confirmation_timeout')
                frame_started=self.clock()
                data,info=self.snapshot(self.clock()+.05)
                if (info['device']!=self.calibration['camera'] or
                    [info['actual_width'],info['actual_height']]!=self.calibration['image_size']):
                    raise ValueError('calibration_source_mismatch')
                frame=output/f'frame-{attempt}';frame.mkdir()
                (frame/'capture.jpg').write_bytes(data)
                source=dict(kind='camera',capture_id=uuid.uuid4().hex,
                            captured_at=info['captured_at'],live=True,
                            age_seconds=self.clock()-info['captured_monotonic'],clock='client_read_completion')
                rid=uuid.uuid4().hex
                request=make_request(data,rid,'book.scan',None,source)
                # Keep original JPEG bytes and full-frame coordinates; constrain text to the shelf.
                left=max(0,int(min(p['xy'][0] for p in self.calibration['vertical']))-60)
                right=min(1920,int(max(p['xy'][0] for p in self.calibration['horizontal']))+160)
                bottom=min(1080,int(max(p['xy'][1] for p in self.calibration['horizontal']))+80)
                request['params']['shelf_roi']=[left,0,right,bottom]
                try:
                    # Bounded single-frame request; keep the overall job deadline.
                    budget=min(60,80-(self.clock()-started))
                    if budget<=0:raise ValueError('book_confirmation_timeout')
                    response=self.client.run(request,frame,total_timeout=budget)
                except NetworkError as error:
                    raise ValueError('ocr_service_unreachable') from error
                except TimeoutError as error:
                    # A request that never reached the PC is different from a
                    # slow queued/running GPU job. Preserve the transport audit.
                    trace_path=frame/'transport.json'
                    trace=json.loads(trace_path.read_text()) if trace_path.exists() else {}
                    code='ocr_service_unreachable' if trace.get('upload_seconds','unknown') is None else 'ocr_processing_timeout'
                    raise ValueError(code) from error
                if response.get('status')!='succeeded':raise ValueError('remote_book_failed')
                result=response['result']
                if (result.get('request_id')!=rid or result.get('image_sha256')!=hashlib.sha256(data).hexdigest()
                    or result.get('source')!=source):raise ValueError('remote_book_result_invalid')
                match=consensus.observe(result,info)
                if alternative is not None and not alternative.confirmed and attempt<=3:
                    alternative_match=alternative.observe(result,info)
                    if alternative_match is not None:alternative_context=(info,source,rid,data)
                (output/'consensus.json').write_text(json.dumps(consensus.info(),indent=2))
                frame_seconds=self.clock()-frame_started
                if match is not None:break
            query_audit=None
            if match is None and not consensus.votes and alternative_match is not None:
                match=alternative_match
                info,source,rid,data=alternative_context
                query_audit=dict(method='repeated_prefix_single_frame_interpretation',requested_title=title,
                                 interpreted_query=interpreted,resolved_title=match['text'],consensus=alternative.info())
                (output/'query-normalization.json').write_text(json.dumps(query_audit,ensure_ascii=False,indent=2))
            if match is None:
                candidates=consensus.frames[-1].get('matching_candidates',0) if consensus.frames else 0
                message=('已读到书名，但检测到多个位置（可能是封面与书脊重复），暂未点灯，请让目标书脊清晰朝向相机。' if candidates>1 else
                         '已读到书名，但复核结果存在冲突，暂未点灯。' if candidates==1 else
                         '本次画面未读到完整主书名，请检查遮挡、反光或拍摄角度。')
                evidence=dict(title=title,found=False,matches=[],indicator_lit=False,motor_action=False,
                              source=source,message=message)
            else:
                if self.clock()-info['captured_monotonic']>70 or self.clock()-started>90:
                    raise ValueError('book_result_too_old')
                box=match['book_box']
                if not (0<=box[0]<box[2]<=1920 and 0<=box[1]<box[3]<=1080):raise ValueError('invalid_book_box')
                try:
                    horizontal_weights,mapping=horizontal_mapping(self.calibration['horizontal'],match)
                except ValueError as error:
                    reasons={
                        'flat_spine_extent_unconfirmed':'已识别到书名，但横放书脊两端边界未确认，定位灯未开启。',
                        'book_projection_outside_measured_leds':'已识别到书名，但位置投影超出已测横向灯带范围，定位灯未开启。',
                        'upright_title_axis_unreliable':'已识别到书名，但书脊方向不可靠，定位灯未开启。',
                        'upright_title_axis_missing':'已识别到书名，但缺少书脊方向信息，定位灯未开启。'}
                    if str(error) not in reasons:raise
                    mapping=dict(method='not_indicated',reason=str(error))
                    evidence=dict(title=title,found=True,matches=[match],source=source,indicator_lit=False,
                                  motor_action=False,horizontal_physical=[],vertical_physical=[],
                                  image_size=[1920,1080],horizontal_mapping=mapping,
                                  geometry_status=str(error),message=reasons[str(error)])
                else:
                    horizontal=sorted(horizontal_weights)
                    vertical=select_axis(self.calibration['vertical'],box,1)
                    pixels=self.black.copy()
                    for i in horizontal:pixels[i]=(max(1,round(255*horizontal_weights[i])),0,0)
                    for i in vertical:pixels[i]=(0,0,255)
                    self.lights.show(SHELF_LED_CHANNEL,pixels,brightness=.10)
                    self.indication_pixels=list(pixels)
                    evidence=dict(title=title,found=True,matches=[match],source=source,indicator_lit=True,
                                  motor_action=False,horizontal_physical=[i+1 for i in horizontal],
                                  vertical_physical=[i+1 for i in vertical],image_size=[1920,1080],
                                  horizontal_mapping=mapping,
                                  geometry_status='experimental_book_box_not_precision_validated',
                                  message='已发送横向红灯、纵向蓝灯定位指令；未验证实际光学点亮。')
                (output/'horizontal-map.json').write_text(json.dumps(mapping,indent=2))
            evidence['source'].update(camera_id=info['device'],freshness='snapshot',
                                      age_at_result_seconds=self.clock()-info['captured_monotonic'])
            evidence.update(remote_request_id=rid,image_sha256=hashlib.sha256(data).hexdigest(),
                            inference_location='local_pc_gpu')
            if query_audit is not None:
                evidence.update(title=match['text'],requested_title=title,query_normalization=query_audit['method'])
                evidence['message']='已去除请求中重复的开头词，并经单帧识别确认书名。'+evidence['message']
            (output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
            return evidence
        except Exception as error:
            self.clear()
            if hasattr(error,'audit'):(output/'anchor-check.json').write_text(json.dumps(error.audit,indent=2))
            (output/'error.json').write_text(json.dumps(dict(error=str(error))))
            raise


def board_adapter(server, token_file, calibration_path, control_root, output_root, snapshot_url):
    """Import board-only libraries once. Hold the LED owner lock for service lifetime."""
    import fcntl
    import sys
    sys.path.append(str(control_root))
    import cv2
    import numpy as np
    from pynq import Overlay
    from adapter_control.hardware import Bridge, Lights
    from ocr_link.client import OCRClient, read_token
    from ocr_link.snapshot import read_snapshot
    owner=Path('/tmp/amd-led2-owner.lock').open('a')
    fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
    overlay=Overlay(str(Path(control_root)/'adapter.bit'),download=True)
    # The service already owns LED2 exclusively. A power cycle clears the PL;
    # restore the known adapter bitstream before touching its command registers.
    if overlay.adapter_bus.mmio.read(8) >> 16 != 0x5a32:
        overlay=Overlay(str(Path(control_root)/'adapter.bit'),download=True)
    lights=Lights(Bridge(overlay.adapter_bus))
    cv2.setNumThreads(1)
    def snapshot(after):
        end=time.monotonic()+6;seen=set()
        while time.monotonic()<end:
            data,info=read_snapshot(snapshot_url)
            if info['captured_monotonic']>after:
                seen.add(info['sequence'])
                if len(seen)>=2:return data,info
            time.sleep(.05)
        raise ValueError('no_fresh_camera_frame')
    from .shelf_calibration import verify_anchors,measure_layout
    def verify(calibration):return verify_anchors(lights,snapshot,calibration)
    adapter=ShelfBookAdapter(OCRClient(server,read_token(token_file),request_timeout=5,total_timeout=20),
                             lights,json.loads(Path(calibration_path).read_text()),output_root,snapshot,verify,
                             calibrator=lambda output:measure_layout(lights,snapshot,output,reference=adapter.calibration),calibration_path=calibration_path)
    adapter.owner,adapter.overlay=owner,overlay
    return adapter
