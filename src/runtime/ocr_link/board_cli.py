"""One explicit board capture/upload command; no OCR or actuator dependencies."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .client import MAX_IMAGE, ClientError, OCRClient, make_request, read_token, save_json


def capture_worker(args):
    capture_started = time.monotonic()
    if args.runtime_path:
        sys.path.insert(0, str(Path(args.runtime_path).resolve()))
    import cv2
    device = int(args.camera) if args.camera.isdigit() else args.camera
    cap = cv2.VideoCapture(device)
    try:
        if not cap.isOpened():
            raise ClientError('camera_open_failed: ' + args.camera)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        frame = None
        for _ in range(3):
            ok, frame = cap.read()
            if not ok or frame is None:
                raise ClientError('camera_read_failed')
        captured_at = datetime.now(timezone.utc).isoformat()
        captured_monotonic = time.monotonic()
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
        if not ok:
            raise ClientError('camera_jpeg_encode_failed')
        Path(args.capture_file).write_bytes(encoded.tobytes())
        save_json(Path(args.capture_file).with_suffix('.json'), {
            'captured_at': captured_at, 'captured_monotonic': captured_monotonic,
            'actual_width': int(frame.shape[1]), 'actual_height': int(frame.shape[0]),
            'clock': 'client_read_completion', 'device': args.camera,
            'worker_capture_seconds': time.monotonic() - capture_started})
    finally:
        cap.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server')
    parser.add_argument('--token-file', type=Path)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--image', type=Path)
    inputs.add_argument('--camera', help='integer camera index or /dev/videoN')
    inputs.add_argument('--snapshot-url',help='Fresh snapshot from the board loopback camera daemon')
    inputs.add_argument('--resume', type=Path, help='existing output directory; reuses its exact request')
    parser.add_argument('--action', choices=('book.find', 'book.scan'), default='book.scan')
    parser.add_argument('--title')
    parser.add_argument('--request-id')
    parser.add_argument('--output', type=Path, default=Path('output/ocr-link'))
    parser.add_argument('--runtime-path')
    parser.add_argument('--request-timeout', type=float, default=10)
    parser.add_argument('--total-timeout', type=float, default=180)
    parser.add_argument('--capture-timeout', type=float, default=15)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--jpeg-quality', type=int, default=95)
    parser.add_argument('--health', action='store_true')
    parser.add_argument('--no-preview', action='store_true')
    parser.add_argument('--capture-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--capture-file', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    execution_start = time.monotonic()
    output, capture_seconds = None, None
    try:
        if args.capture_worker:
            capture_worker(args)
            return 0
        if not args.server or not args.token_file:
            parser.error('--server and --token-file are required')
        client = OCRClient(args.server, read_token(args.token_file), args.request_timeout, args.total_timeout)
        if args.health:
            print(json.dumps(client.health(), ensure_ascii=False, indent=2))
            return 0
        if args.resume:
            output = args.resume
            payload = json.loads((output / 'request.json').read_text(encoding='utf-8'))
        else:
            if not args.image and args.camera is None and not args.snapshot_url:
                parser.error('choose --image, --camera or --snapshot-url')
            request_id = args.request_id or uuid.uuid4().hex
            # Validate before constructing a filesystem path.
            from .client import REQUEST_ID
            if not REQUEST_ID.fullmatch(request_id):
                raise ClientError('invalid request_id')
            output = args.output / request_id
            output.mkdir(parents=True, exist_ok=False)
            capture_id = uuid.uuid4().hex
            if args.image:
                with args.image.open('rb') as image_file:
                    data = image_file.read(MAX_IMAGE + 1)
                source = dict(kind='image', capture_id=capture_id, captured_at=None,
                              live=False, age_seconds=0.0, clock='unknown')
            elif args.snapshot_url:
                from .snapshot import read_snapshot
                capture_started=time.monotonic()
                data,info=read_snapshot(args.snapshot_url)
                capture_seconds=time.monotonic()-capture_started
                image_path=output/'capture.jpg';image_path.write_bytes(data)
                save_json(image_path.with_suffix('.json'),info)
                source=dict(kind='camera',capture_id=capture_id,captured_at=info['captured_at'],live=True,
                            age_seconds=time.monotonic()-info['captured_monotonic'],clock='client_read_completion')
            else:
                if args.width <= 0 or args.height <= 0 or not 1 <= args.jpeg_quality <= 100 or not 0 < args.capture_timeout <= 120:
                    raise ClientError('invalid camera dimensions, quality or timeout (1..120 seconds)')
                image_path = output / 'capture.jpg'
                command = [sys.executable, '-m', 'ocr_link.board_cli', '--capture-worker', '--camera', args.camera,
                           '--capture-file', str(image_path), '--width', str(args.width), '--height', str(args.height),
                           '--jpeg-quality', str(args.jpeg_quality)]
                if args.runtime_path:
                    command += ['--runtime-path', args.runtime_path]
                capture_started = time.monotonic()
                try:
                    subprocess.run(command, check=True, timeout=args.capture_timeout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                except subprocess.TimeoutExpired as exc:
                    raise ClientError('camera capture timed out; worker was terminated') from exc
                except subprocess.CalledProcessError as exc:
                    raise ClientError('camera worker failed: ' + exc.stderr.decode('utf-8', errors='replace')[-2000:]) from exc
                capture_seconds = time.monotonic() - capture_started
                data = image_path.read_bytes()
                info = json.loads(image_path.with_suffix('.json').read_text(encoding='utf-8'))
                source = dict(kind='camera', capture_id=capture_id, captured_at=info['captured_at'], live=True,
                              age_seconds=max(0.0, time.monotonic() - info['captured_monotonic']), clock='client_read_completion')
            payload = make_request(data, request_id, args.action, args.title, source)
        state = client.run(payload, output, download_preview=not args.no_preview)
        print(json.dumps({'output': str(output.resolve()), 'response': state}, ensure_ascii=False, indent=2))
        return 0 if state['status'] == 'succeeded' else 2
    except (ClientError, TimeoutError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if not args.capture_worker and output is not None and output.is_dir():
            save_json(output / 'execution.json', {'v': 1, 'cli_total_seconds': time.monotonic() - execution_start,
                                                 'capture_seconds': capture_seconds,
                                                 'capture_subprocess_seconds': capture_seconds if args.camera is not None else None,
                                                 'capture_mode': 'snapshot' if args.snapshot_url else ('subprocess' if args.camera is not None else None),
                                                 'resumed': args.resume is not None})


if __name__ == '__main__':
    raise SystemExit(main())
