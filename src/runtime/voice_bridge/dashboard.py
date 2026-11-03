"""Local browser preview. Hardware outputs remain disconnected."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

try:
    from .pynq_service import DeskService, decode_frame, MAX_FRAME
except ImportError:
    from pynq_service import DeskService, decode_frame, MAX_FRAME


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8765, service=None):
        self.service = service if service is not None else DeskService(simulate=True)
        self.service_lock = threading.RLock()
        super().__init__(('127.0.0.1', port), DashboardHandler)

    def server_close(self):
        super().server_close()
        with self.service_lock:
            self.service.close()


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def allowed_origin(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return (self.headers.get('Host') == expected and
                self.headers.get('Origin', f'http://{expected}') == f'http://{expected}')

    def send_payload(self, status, payload, content_type='application/json; charset=utf-8'):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed_origin():
            return self.send_payload(403, {'error': 'local_origin_required'})
        if self.path == '/api/events':
            with self.server.service_lock:
                events = self.server.service.poll_events()
            return self.send_payload(200, {'events': events})
        if self.path != '/':
            return self.send_payload(404, {'error': 'not_found'})
        self.send_payload(200, Path(__file__).with_name('dashboard.html').read_bytes(), 'text/html; charset=utf-8')

    def do_POST(self):
        if not self.allowed_origin():
            return self.send_payload(403, {'error': 'local_origin_required'})
        if self.path != '/api/request':
            return self.send_payload(404, {'error': 'not_found'})
        if self.headers.get_content_type() != 'application/json':
            return self.send_payload(415, {'error': 'json_required'})
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            return self.send_payload(400, {'error': 'invalid_length'})
        if not 0 < length <= MAX_FRAME:
            return self.send_payload(413, {'error': 'frame_too_large'})
        self.connection.settimeout(5)
        try:
            body = self.rfile.read(length)
        except TimeoutError:
            return self.send_payload(408, {'error': 'read_timeout'})
        if len(body) != length:
            return self.send_payload(400, {'error': 'incomplete_body'})
        with self.server.service_lock:
            result = decode_frame(self.server.service, body)
        self.send_payload(400 if result.get('type') == 'error' else 200, result)


def main():
    parser = argparse.ArgumentParser(description='智能学习桌本地预览')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--book-image', help='用于离线找书验证的本地照片')
    parser.add_argument('--db-path', default='desk_records.sqlite3', help='记录数据库文件')
    args = parser.parse_args()
    service = DeskService(simulate=True, book_image=args.book_image, db_path=args.db_path)
    server = DashboardServer(args.port, service)
    print(f'本地预览：http://127.0.0.1:{server.server_port}（灯光仅预览，未连接硬件）')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
