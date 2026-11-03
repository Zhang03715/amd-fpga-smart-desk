"""Loopback-only visual detector ingress; events stay in the owning DeskService.

HTTP acceptance means queued, not a reminder or an already processed sample.
Only drain(), called by the service owner thread, touches FeatureService.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from queue import Queue, Empty, Full
import threading


class PostureIngress:
    def __init__(self, port=8766, queue_limit=128):
        self.queue = Queue(maxsize=queue_limit)
        self.server = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
        self.server.daemon_threads = True
        self.server.ingress = self
        self.thread = None

    @property
    def port(self):
        return self.server.server_port

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True,
                                       name='posture-ingress')
        self.thread.start()
        return self

    def close(self):
        if self.thread:
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()

    def submit(self, params):
        if not isinstance(params, dict):
            raise ValueError('invalid_params')
        if params.get('source') != 'detector':
            raise ValueError('detector_source_required')
        if params.get('classification') not in ('good', 'bad', 'unknown'):
            raise ValueError('invalid_classification')
        if params.get('source_kind') not in ('camera', 'video', 'image'):
            raise ValueError('invalid_source_kind')
        session = params.get('session_id')
        if not isinstance(session, str) or not session.strip() or len(session) > 80:
            raise ValueError('invalid_session_id')
        if type(params.get('frame_id')) is not int or params['frame_id'] < 0:
            raise ValueError('invalid_frame_id')
        captured = params.get('captured_at')
        if type(captured) not in (int, float) or not math.isfinite(captured):
            raise ValueError('invalid_captured_at')
        # Retain confidence/reasons/metrics for diagnostics, but never treat
        # these optional values as a replacement for detector classification.
        self.queue.put_nowait(dict(params))
        return {'accepted': True, 'queued': True, 'processed': False}

    def drain(self, service):
        results = []
        while True:
            try:
                sample = self.queue.get_nowait()
            except Empty:
                break
            try:
                results.append(service.execute('posture.update', sample))
            except ValueError as exc:
                results.append({'error': str(exc)})
        return results


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload):
        data = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != expected or self.headers.get('Origin') is not None:
            return self.reply(403, {'error': 'local_detector_required'})
        if self.path != '/posture/sample':
            return self.reply(404, {'error': 'not_found'})
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415, {'error': 'json_required'})
        try:
            length = int(self.headers.get('Content-Length', ''))
            if not 0 < length <= 16384:
                return self.reply(413, {'error': 'invalid_length'})
            self.connection.settimeout(2)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('incomplete_body')
            payload = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_json')))
            result = self.server.ingress.submit(payload)
        except Full:
            return self.reply(429, {'error': 'posture_queue_full'})
        except (ValueError, UnicodeError, TimeoutError, RecursionError) as exc:
            return self.reply(400, {'error': str(exc) if isinstance(exc, ValueError) else 'invalid_body'})
        self.reply(202, result)
