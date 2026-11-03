"""Read-only authenticated LAN pictures, separate from the S3 command channel."""
import hmac,secrets,socket,threading,time,json
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs

class PostureImages:
    def __init__(self,control,port=8768,host='0.0.0.0'):
        self.control=control;self.token=secrets.token_urlsafe(32)
        self.alert={}
        self.server=ThreadingHTTPServer((host,port),Handler)
        self.server.images=self;self.server.daemon_threads=True
    def start(self):
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start();return self
    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
    def info(self):
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.connect(('8.8.8.8',80));ip=sock.getsockname()[0]
        except OSError:return {}
        base='http://%s:%d/'%(ip,self.server.server_port)
        return {name:base+route+'?token='+self.token for name,route in
                [('preview_url','preview.jpg'),('baseline_url','baseline.jpg'),('status_url','status'),('paper_url','paper.jpg')]}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass  # URLs carry a short-lived viewing credential.
    def do_GET(self):
        owner=self.server.images;url=urlsplit(self.path)
        if not hmac.compare_digest(parse_qs(url.query).get('token',[''])[0],owner.token):
            self.send_error(401);return
        if url.path=='/status':
            detector=owner.control.status();alert=dict(owner.alert)
            stale=time.monotonic()-alert.pop('updated_monotonic',-100)>3
            if stale:alert=dict(classification='unknown',stale=True,red_light_active=None,red_light_error='status_not_fresh')
            result=dict(alert,detector=detector)
            data=json.dumps(result).encode()
            self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.send_header('Access-Control-Allow-Origin','*');self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
            return
        if url.path not in ('/preview.jpg','/baseline.jpg','/paper.jpg'):
            self.send_error(404);return
        path=owner.control.root/('latest.jpg' if url.path=='/preview.jpg' else 'paper-latest.jpg' if url.path=='/paper.jpg' else 'baseline.jpg')
        try:
            if url.path=='/preview.jpg' and (not owner.control.status()['available'] or time.time()-path.stat().st_mtime>8):
                self.send_error(503);return
            if path.stat().st_size>(2*1024*1024 if url.path=='/paper.jpg' else 512*1024):raise ValueError('oversized image')
            data=path.read_bytes()
            if not data.startswith(b'\xff\xd8'):raise ValueError('invalid JPEG')
        except (OSError,ValueError):self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type','image/jpeg')
        self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        self.send_header('Referrer-Policy','no-referrer');self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass
