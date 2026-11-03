"""Image/video/USB-camera posture prototype, using the existing reminder service via IPC."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import threading
import time
import uuid

from .runtime import FrozenFrameGuard, send_sample, unknown
from .rules import extract_features, calibrate, classify


class LatestCamera:
    """Continuously read, overwrite older frames, never resubmit one frame ID."""
    def __init__(self, cap):
        self.cap = cap
        self.lock = threading.Lock()
        self.latest = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        index = 0
        while not self.stop.is_set():
            ok, image = self.cap.read()
            if not ok:
                self.stop.wait(.05)
                continue
            index += 1
            item = (index, image, time.time(), time.monotonic())
            with self.lock:
                self.latest = item

    def get(self):
        with self.lock:
            return self.latest

    def close(self):
        self.stop.set()
        self.cap.release()
        self.thread.join(timeout=2)


def annotate(image, landmarks, result, cv2):
    canvas = image.copy()
    h, w = canvas.shape[:2]
    color = {'good': (0, 200, 0), 'bad': (0, 0, 255), 'unknown': (0, 180, 255)}[result['classification']]
    for pose in landmarks:
        for a, b in ((7, 11), (8, 12), (11, 12), (11, 23), (12, 24), (23, 24)):
            if min(pose[a]['visibility'], pose[b]['visibility']) >= .5:
                cv2.line(canvas, (int(pose[a]['x']*w), int(pose[a]['y']*h)),
                         (int(pose[b]['x']*w), int(pose[b]['y']*h)), color, 2)
        for p in pose:
            if p['visibility'] >= .5 and 0 <= p['x'] <= 1 and 0 <= p['y'] <= 1:
                cv2.circle(canvas, (int(p['x']*w), int(p['y']*h)), 3, color, -1)
    lines = [f"{result['classification']}  keypoint confidence={result['confidence']:.2f}",
             ' / '.join(result['reasons']) or 'within personal baseline']
    lines += [f'{k}: {v:.3f}' for k, v in result['metrics'].items() if isinstance(v, (float, int))][:8]
    for i, line in enumerate(lines):
        cv2.putText(canvas, line, (12, 25 + i*23), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1, cv2.LINE_AA)
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--image', type=Path)
    source.add_argument('--video', type=Path)
    source.add_argument('--camera', type=int)
    parser.add_argument('--model', type=Path, default=Path('models/posture/pose_landmarker_lite.task'))
    parser.add_argument('--view', choices=['front', 'side'], default='front')
    parser.add_argument('--camera-id', default='desk-camera')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--calibrate', type=Path, help='Record known-good samples and save personal baseline; no reminders')
    parser.add_argument('--calibration-samples', type=int, default=30)
    parser.add_argument('--config', type=Path, help='JSON rule thresholds; independent of reminder duration/cooldown')
    parser.add_argument('--sample-hz', type=float, default=2)
    parser.add_argument('--max-age', type=float, default=2)
    parser.add_argument('--max-frames', type=int, default=0)
    parser.add_argument('--endpoint', help='Existing service loopback /posture/sample endpoint; never starts a second service')
    parser.add_argument('--display', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('offline_results/posture_manual'))
    args = parser.parse_args()
    if not math.isfinite(args.sample_hz) or not 0 < args.sample_hz <= 30 or not math.isfinite(args.max_age) or args.max_age <= 0:
        parser.error('sample-hz must be (0,30], max-age must be positive')
    if args.calibration_samples < 15 or args.max_frames < 0:
        parser.error('calibration-samples >=15; max-frames >=0')
    if args.calibrate and (args.image or args.baseline):
        parser.error('calibration needs multiple video/camera frames and no existing baseline')
    import cv2
    import numpy as np
    import mediapipe as mp
    config = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
    config['max_age'] = args.max_age
    baseline = json.loads(args.baseline.read_text(encoding='utf-8-sig')) if args.baseline else None
    args.output.mkdir(parents=True, exist_ok=True)
    kind = 'image' if args.image else 'video' if args.video else 'camera'
    session = uuid.uuid4().hex
    video_mode = kind != 'image'
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(args.model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO if video_mode else mp.tasks.vision.RunningMode.IMAGE,
        num_poses=2, min_pose_detection_confidence=.6, min_pose_presence_confidence=.6,
        min_tracking_confidence=.6)
    cap = None
    camera = None
    if kind != 'image':
        cap = cv2.VideoCapture(args.camera if kind == 'camera' else str(args.video))
        if not cap.isOpened():
            raise RuntimeError('capture_open_failed')
        if kind == 'camera':
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            camera = LatestCamera(cap)
    fps = cap.get(cv2.CAP_PROP_FPS) if kind == 'video' else 0
    if kind == 'video' and (not math.isfinite(fps) or fps <= 0):
        cap.release()
        raise RuntimeError('video_fps_missing; cannot invent source timestamps')
    guard = FrozenFrameGuard(args.max_age)
    samples, timings, calibration_hashes = [], [], set()
    processed, index, last_id, last_timestamp = 0, 0, 0, -1
    started = time.monotonic()
    log = (args.output / 'samples.jsonl').open('w', encoding='utf-8')
    try:
        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as detector:
            while True:
                media_seconds = None
                if kind == 'image':
                    if processed: break
                    image = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if image is None: raise RuntimeError('image_read_failed')
                    index = 1; captured_at, captured_mono = time.time(), time.monotonic()
                elif kind == 'video':
                    ok, image = cap.read()
                    if not ok: break
                    index += 1
                    media_seconds = (index-1)/fps
                    if index > 1 and media_seconds < processed/args.sample_hz: continue
                    captured_at, captured_mono = time.time(), time.monotonic()
                else:
                    item = camera.get()
                    if item is None or item[0] == last_id:
                        if time.monotonic()-started > args.max_age and (item is None or time.monotonic()-item[3] > args.max_age):
                            # A failure observation keeps the last actual capture time, not invented fresh pixels.
                            failure = dict(unknown('capture_unavailable_or_stale'), source='detector',
                                           source_kind='camera', captured_at=item[2] if item else 0,
                                           session_id=session, frame_id=last_id+1, source_uri=f'usb-camera:{args.camera}')
                            if args.endpoint and not args.calibrate:
                                try: failure['delivery'] = send_sample(args.endpoint, failure)
                                except Exception as exc: failure['delivery_error'] = str(exc)
                            log.write(json.dumps(failure)+'\n'); log.flush()
                            if item:
                                cv2.imencode('.jpg', annotate(item[1], [], failure, cv2))[1].tofile(args.output/'annotated_last.jpg')
                            print('camera has no fresh frame; reminder service will become unknown', file=sys.stderr)
                            break
                        time.sleep(.02); continue
                    index, image, captured_at, captured_mono = item
                    last_id = index
                inference_start = time.monotonic()
                timestamp = max(last_timestamp+1, int((media_seconds if kind == 'video' else captured_mono-started)*1000))
                last_timestamp = timestamp
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)))
                prediction = detector.detect_for_video(mp_image, timestamp) if video_mode else detector.detect(mp_image)
                poses = [[{k: float(getattr(p, k)) for k in ('x','y','z','visibility','presence')} for p in pose] for pose in prediction.pose_landmarks]
                age = time.monotonic()-captured_mono
                if kind == 'camera' and guard.frozen(image.tobytes(), captured_mono): result = unknown('frozen_frame')
                elif len(poses) != 1: result = unknown('no_person' if not poses else 'multiple_people')
                elif args.calibrate:
                    feature = extract_features(poses[0], (image.shape[1],image.shape[0]), args.view, config)
                    digest = hashlib.sha256(image.tobytes()).digest()
                    if feature['valid'] and age <= args.max_age and digest not in calibration_hashes:
                        samples.append(feature)
                        calibration_hashes.add(digest)
                    result = unknown(f'calibrating_{len(samples)}_of_{args.calibration_samples}')
                    result['metrics'], result['confidence'] = feature['metrics'], feature['confidence']
                else:
                    result = classify(poses[0], (image.shape[1],image.shape[0]), baseline, view=args.view,
                                      age_seconds=age, config=config, camera_id=args.camera_id)
                if age > args.max_age: result = unknown('stale_frame')
                elapsed = time.monotonic()-inference_start
                timings.append(elapsed)
                sample = dict(result, source='detector', source_kind=kind, captured_at=captured_at,
                              session_id=session, frame_id=index, media_seconds=media_seconds,
                              source_uri=str(args.image or args.video) if kind != 'camera' else f'usb-camera:{args.camera}',
                              frame_age_seconds=age,
                              camera_id=args.camera_id, view=args.view, inference_seconds=elapsed)
                if args.endpoint and not args.calibrate:
                    try: sample['delivery'] = send_sample(args.endpoint, sample)
                    except Exception as exc: sample['delivery_error'] = str(exc); print(f'IPC failed: {exc}', file=sys.stderr)
                log.write(json.dumps(sample, ensure_ascii=False, allow_nan=False)+'\n'); log.flush()
                canvas = annotate(image, poses, result, cv2)
                cv2.imencode('.jpg', canvas)[1].tofile(args.output / 'annotated_last.jpg')
                processed += 1
                if args.display:
                    cv2.imshow('Posture: q quits; baseline requires known-good posture', canvas)
                    if cv2.waitKey(1) & 0xff == ord('q'): break
                if args.calibrate and len(samples) >= args.calibration_samples:
                    reference = calibrate(samples, args.view, config=config, camera_id=args.camera_id)
                    reference.update(created_at=time.time(), source_kind=kind, thresholds=config,
                                     model_path=str(args.model))
                    args.calibrate.parent.mkdir(parents=True,exist_ok=True)
                    args.calibrate.write_text(json.dumps(reference,indent=2),encoding='utf-8')
                    print(f'baseline saved: {args.calibrate}'); break
                if args.max_frames and processed >= args.max_frames: break
                if kind == 'camera': time.sleep(max(0,1/args.sample_hz-(time.monotonic()-inference_start)))
    finally:
        log.close()
        if camera: camera.close()
        elif cap: cap.release()
        if args.display: cv2.destroyAllWindows()
        summary = {'processed_frames':processed,'source_kind':kind,'view':args.view,'model':str(args.model),
                   'mean_processing_seconds':sum(timings)/len(timings) if timings else None,
                   'calibration_valid_samples':len(samples),'calibration_saved':bool(args.calibrate and len(samples)>=args.calibration_samples),
                   'accuracy':'not measured; no labelled sitting data', 'backend':'MediaPipe CPU'}
        (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary))
    if args.calibrate and len(samples)<args.calibration_samples:
        raise RuntimeError('insufficient_valid_calibration_samples; baseline not saved')


if __name__ == '__main__':
    main()
