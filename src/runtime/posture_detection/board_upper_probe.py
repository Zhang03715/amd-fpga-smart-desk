"""Bounded Z2 diagnostic; shares camera0's fresh preview, never opens its device.

No baseline collection or reminder delivery is performed by this probe.
"""
import io
import argparse
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import time

import cv2
import numpy as np
from upper_body import assess, calibrate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--calibrate', action='store_true')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--frames', type=int, default=5)
    parser.add_argument('--simple-front', action='store_true')
    parser.add_argument('--front-evidence-filter', action='store_true',
                        help='Require exactly one front candidate with valid face/shoulder evidence')
    options = parser.parse_args()
    evaluate = assess
    if options.simple_front:
        from upper_body import assess_simple as evaluate
    baseline = json.loads(options.baseline.read_text()) if options.baseline else None
    if options.calibrate and baseline is not None:
        parser.error('Calibration and assessment are separate runs')
    root = Path('/home/xilinx/z2-posture-int8')
    out = Path(__file__).parent/'results'
    out.mkdir(exist_ok=True)
    sources = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = (proc/'cmdline').read_bytes().split(b'\0')
            if b'adapter_control.camera_preview' in args and b'--worker' in args:
                i = args.index(b'--worker')
                if args[i+1] == b'0':sources.append(Path(args[i+2].decode()))
        except OSError:
            pass
    assert len(sources) == 1, sources
    cv2.setNumThreads(1)
    sys.path.insert(0, str(root/'board'))
    from run import letterbox
    records = []
    samples = []
    with (out/'worker.log').open('w') as log:
        worker = subprocess.Popen([str(root/'bin/z2-pose'), '--model-dir', str(root/'models'),
                                   '--threads', '2'], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=log, bufsize=0)
        previous = None
        try:
            for _ in range(25 if options.calibrate else options.frames):
                packet = sources[0].read_bytes()
                captured, sequence = struct.unpack('<dQ', packet[:16])
                assert sequence != previous and 0 <= time.monotonic()-captured < 2
                previous = sequence
                frame = cv2.imdecode(np.frombuffer(packet[16:], dtype=np.uint8), cv2.IMREAD_COLOR)
                inp, scale, px, py = letterbox(frame)
                started = time.monotonic()
                data = inp.tobytes(); offset = 0
                while offset < len(data):offset += os.write(worker.stdin.fileno(), data[offset:])
                if not select.select([worker.stdout], [], [], 30)[0]:raise TimeoutError('Pose worker')
                result = json.loads(worker.stdout.readline())
                people = result['people']
                # Multiple people are ambiguous; do not silently select a user.
                points = []
                candidates = [[[(x-px)/scale, (y-py)/scale, c] for x,y,c in p['keypoints']] for p in people]
                eligible = list(range(len(people)))
                if options.front_evidence_filter:
                    from upper_body import eligible_front_candidates
                    eligible = eligible_front_candidates(candidates,(frame.shape[1],frame.shape[0]))
                if len(eligible) == 1:
                    points = candidates[eligible[0]]
                age = time.monotonic()-captured
                assessment = evaluate(points, (frame.shape[1],frame.shape[0]), baseline,
                                    age_seconds=age)
                if options.calibrate:
                    if assessment['status'] == 'calibration_needed':
                        samples.append(assessment['metrics'])
                    else:
                        samples.clear()
                record = dict(sequence=sequence, age_seconds=age,
                              captured_monotonic=captured,
                              elapsed_seconds=time.monotonic()-started,
                              inference_ms=result.get('inference_ms'), people_count=len(people),
                              eligible_candidates=eligible,
                              candidate_quality=[dict(index=i,confidence=p.get('confidence'),
                                      front_min_confidence=min(candidates[i][j][2] for j in (0,5,6)))
                                      for i,p in enumerate(people)],
                              assessment=assessment)
                records.append(record)
                temporary = out/'status.part'
                temporary.write_text(json.dumps(record))
                os.replace(temporary, out/'status.json')
                print(json.dumps(record), flush=True)
                for i in (0,5,6):
                    if points and points[i][2] >= .65:
                        x,y,_ = points[i];cv2.circle(frame,(int(x),int(y)),3,(0,255,0),-1)
                cv2.putText(frame,assessment['status'],(5,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1)
                cv2.imwrite(str(out/'latest.jpg'),frame)
                (out/'records.json').write_text(json.dumps(records,indent=2))
                if options.calibrate and len(samples) >= 15:
                    baseline = calibrate(samples, 'camera0')
                    baseline['preview_path'] = str(sources[0])
                    baseline['created_at'] = time.time()
                    path = out/('baseline-%d.json' % time.time_ns())
                    path.write_text(json.dumps(baseline, indent=2))
                    print('CALIBRATION_SAVED', str(path), flush=True)
                    break
            else:
                if options.calibrate:raise RuntimeError('Not enough consecutive valid calibration samples')
        finally:
            worker.stdin.close();worker.terminate()
            try:worker.wait(timeout=3)
            except subprocess.TimeoutExpired:worker.kill();worker.wait()


if __name__ == '__main__':main()
