import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hmac
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time

from .client import read_token, save_json
from .protocol import ID, MAX_BODY, ProtocolError, decode_json, validate


class JobStore:
    def __init__(self, root, pipeline, max_pending=2, max_jobs=64, ttl_seconds=180,
                 max_image_bytes=8*1024*1024, clock=time.monotonic):
        self.root = Path(root)
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0 or min(max_pending,max_jobs,max_image_bytes) <= 0:
            raise ValueError('invalid job limits')
        self.root.mkdir(parents=True, exist_ok=True)
        self.pipeline, self.max_pending, self.max_jobs = pipeline, max_pending, max_jobs
        self.ttl, self.max_image_bytes, self.clock = ttl_seconds, max_image_bytes, clock
        self.lock, self.jobs = threading.RLock(), {}
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ocr-gpu')
        # Completed jobs survive a service restart without silently repeating OCR.
        for directory in sorted(self.root.iterdir()):
            if len(self.jobs) >= self.max_jobs:
                break
            if not directory.is_dir() or not ID.fullmatch(directory.name):
                continue
            try:
                metadata = json.loads((directory/'request.json').read_text(encoding='utf-8'))
                state = json.loads((directory/'response.json').read_text(encoding='utf-8'))
                if metadata['request_id'] != directory.name or state['request_id'] != directory.name:
                    continue
                if state['status'] in ('queued', 'running'):
                    state = dict(v=1, request_id=directory.name, status='failed', error='ServerRestart',
                                 message='Server restarted before completion; submit a new explicit request')
                fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True, ensure_ascii=False,
                                                         allow_nan=False).encode()).hexdigest()
                self.jobs[directory.name] = dict(state=state, fingerprint=fingerprint, directory=directory,
                                                received=self.clock(), metadata=metadata,finished=True)
                self._persist(directory.name)
            except (OSError, ValueError, KeyError):
                continue

    def _disk_job(self,rid):
        """Read an evicted result without rerunning OCR or overwriting evidence."""
        if not isinstance(rid,str) or not ID.fullmatch(rid):raise ProtocolError(404,'unknown job')
        directory=self.root/rid
        try:
            metadata=json.loads((directory/'request.json').read_text(encoding='utf-8'))
            state=json.loads((directory/'response.json').read_text(encoding='utf-8'))
            if metadata['request_id']!=rid or state['request_id']!=rid:raise ValueError('identity mismatch')
            fingerprint=hashlib.sha256(json.dumps(metadata,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
            if state['status'] in ('queued','running'):
                state=dict(v=1,request_id=rid,status='failed',error='ServerRestart',
                           message='Server restarted before completion; submit a new explicit request')
                save_json(directory/'response.json',state)
            return dict(state=state,fingerprint=fingerprint)
        except (OSError,ValueError,KeyError):raise ProtocolError(404,'unknown or incomplete persisted job')

    def _cache_room(self):
        # Completed artifacts remain on disk. Bound only the in-memory cache;
        # active workers are pinned until their terminal response is persisted.
        while len(self.jobs)>=self.max_jobs:
            victim=next((rid for rid,j in self.jobs.items() if j.get('finished',False)),None)
            if victim is None:raise ProtocolError(429,'OCR cache full with active jobs')
            del self.jobs[victim]

    def submit(self, payload):
        data, suffix, metadata, fingerprint = validate(payload, self.max_image_bytes)
        rid = payload['request_id']
        with self.lock:
            if rid in self.jobs:
                if self.jobs[rid]['fingerprint'] != fingerprint:
                    raise ProtocolError(409, 'request_id already belongs to different content')
                return deepcopy(self.jobs[rid]['state'])
            if (self.root/rid).exists():
                try:old=self._disk_job(rid)
                except ProtocolError:raise ProtocolError(409,'request_id belongs to incomplete persisted data; use a new id')
                if old['fingerprint']!=fingerprint:raise ProtocolError(409,'request_id already belongs to different content')
                return deepcopy(old['state'])
            active = sum(j['state']['status'] in ('queued', 'running') for j in self.jobs.values())
            if active >= self.max_pending:
                raise ProtocolError(429, 'OCR queue full')
            self._cache_room()
            directory = self.root/rid
            directory.mkdir()
            image = directory/('input'+suffix)
            image.write_bytes(data)
            save_json(directory/'request.json', metadata)
            state = dict(v=1, request_id=rid, status='queued')
            self.jobs[rid] = dict(state=state, fingerprint=fingerprint, directory=directory,
                                  received=self.clock(), metadata=metadata,finished=False)
            self._persist(rid)
            self.worker.submit(self._run, rid, image)
            return deepcopy(state)

    def _persist(self, rid):
        job = self.jobs[rid]
        save_json(job['directory']/'response.json', job['state'])

    def _run(self, rid, image):
        with self.lock:
            job = self.jobs[rid]
            job['state']['status'] = 'running'
            queue_seconds = self.clock()-job['received']
            self._persist(rid)
        try:
            if queue_seconds > self.ttl:
                raise TimeoutError('request expired in queue')
            result = self.pipeline(image, deepcopy(job['metadata']), job['directory'])
            elapsed = self.clock()-job['received']
            if elapsed > self.ttl:
                raise TimeoutError('request expired during processing')
            result.update(request_id=rid, image_sha256=job['metadata']['image']['sha256'],
                          image_dimensions=job['metadata']['image']['dimensions'],
                          source=deepcopy(job['metadata']['source']),
                          timing={'queue_seconds':queue_seconds, 'server_elapsed_seconds':elapsed,
                                  'capture_age_at_result_seconds':job['metadata']['source']['age_seconds']+elapsed,
                                  'capture_age_basis':'declared_age_plus_server_elapsed_lower_bound_excludes_upload_and_pre_receipt_retries'},
                          indicator_lit=False, motor_action=False)
            # Serialization rejects non-finite results rather than returning invalid JSON.
            json.dumps(result, allow_nan=False)
            with self.lock:
                job['state'].update(status='succeeded', result=result)
        except Exception as exc:
            with self.lock:
                job['state'].update(status='failed', error=type(exc).__name__,
                                    message='OCR processing failed or expired; inspect server job logs')
            (job['directory']/'error.log').write_text(__import__('traceback').format_exc(), encoding='utf-8')
        finally:
            with self.lock:
                self._persist(rid)
                self.jobs[rid]['finished']=True

    def status(self, rid):
        with self.lock:
            if rid not in self.jobs:
                return deepcopy(self._disk_job(rid)['state'])
            return deepcopy(self.jobs[rid]['state'])

    def preview(self, rid):
        if self.status(rid)['status'] != 'succeeded':
            raise ProtocolError(409, 'preview not ready')
        path = self.root/rid/'preview.jpg'
        if not path.is_file():
            raise ProtocolError(404, 'no preview')
        return path

    def close(self):
        self.worker.shutdown(wait=True, cancel_futures=False)
        if hasattr(self.pipeline,'close'):self.pipeline.close()


def make_handler(app, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def reply(self, status, value, binary=False):
            body = value if binary else json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            compressed=not binary and len(body)>2048 and 'gzip' in self.headers.get('Accept-Encoding','').split(',')
            if compressed:
                import gzip
                body=gzip.compress(body,compresslevel=3)
            self.send_response(status)
            if compressed:self.send_header('Content-Encoding','gzip')
            self.send_header('Vary','Accept-Encoding')
            self.send_header('Content-Type', 'image/jpeg' if binary else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)

        def auth(self):
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer '+token).encode()):
                raise ProtocolError(401, 'authentication required')

        def handle_request(self, post=False):
            try:
                self.auth()
                if post:
                    if self.path != '/v1/jobs':
                        raise ProtocolError(404, 'unknown endpoint')
                    if self.headers.get('Transfer-Encoding'):
                        raise ProtocolError(400, 'chunked uploads unsupported')
                    try:
                        length = int(self.headers['Content-Length'])
                    except (ValueError, TypeError):
                        raise ProtocolError(411, 'Content-Length required')
                    if not 0 < length <= MAX_BODY:
                        raise ProtocolError(413, 'request body too large')
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ProtocolError(400, 'incomplete body')
                    self.reply(202, app.submit(decode_json(body)))
                elif self.path == '/v1/health':
                    self.reply(200, dict(v=1, status='ready', inference_location='local_pc_gpu',
                                         actions=['book.scan', 'book.find','paper.classify'],
                                         worker_warm=bool(getattr(getattr(app.pipeline,'resident',None),'warmed',False))))
                else:
                    parts = self.path.split('/')
                    if len(parts) not in (4,5) or parts[1:3] != ['v1','jobs'] or not ID.fullmatch(parts[3]) or (len(parts)==5 and parts[4]!='preview'):
                        raise ProtocolError(404, 'unknown endpoint')
                    if len(parts)==5:
                        self.reply(200, app.preview(parts[3]).read_bytes(), binary=True)
                    else:
                        self.reply(200, app.status(parts[3]))
            except ProtocolError as exc:
                self.reply(exc.status, dict(v=1, error=str(exc)))
            except (TimeoutError, ConnectionError, BrokenPipeError):
                self.close_connection = True
            except Exception:
                self.reply(500, dict(v=1, error='internal server error'))

        def do_POST(self):
            self.handle_request(post=True)

        def do_GET(self):
            self.handle_request()
    return Handler


def main():
    from .pipeline import GPUPipeline, ROOT
    parser = argparse.ArgumentParser(description='Single GPU worker for explicit Z2 OCR jobs')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, default=ROOT/'output/ocr-link-jobs')
    parser.add_argument('--python', type=Path, default=ROOT/'.venv-gpu/Scripts/python.exe')
    parser.add_argument('--options', type=Path, default=ROOT/'board_ocr/paddle_lite_trial/v6_tiny/pc_options_flat_fix_v2.json')
    parser.add_argument('--v4-model', type=Path, default=ROOT/'.venv/Lib/site-packages/rapidocr_onnxruntime/models/ch_PP-OCRv4_rec_infer.onnx')
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--resident-models',action='store_true',help='Keep isolated CUDA model sessions resident between jobs')
    parser.add_argument('--upright-geometry-experiment',action='store_true',
                        help='Opt in to development upright geometry; not yet validated for production')
    args = parser.parse_args()
    import onnxruntime as ort
    ort.preload_dlls(directory='')
    if 'CUDAExecutionProvider' not in ort.get_available_providers():
        parser.error('CUDA provider unavailable; refusing CPU fallback')
    app = JobStore(args.output_root, GPUPipeline(args.python,args.options,args.v4_model,args.timeout,
                                               upright_geometry=args.upright_geometry_experiment,
                                               resident_models=args.resident_models),ttl_seconds=args.timeout)
    server = ThreadingHTTPServer((args.host,args.port),make_handler(app,read_token(args.token_file)))
    print(f'OCR server listening on {args.host}:{args.port}; one GPU worker', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == '__main__':
    main()
