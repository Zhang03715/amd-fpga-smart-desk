"""Keep one Linux camera open; serve fresh full-resolution JPEG on loopback."""
import argparse
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--camera',default='0')
    p.add_argument('--width',type=int,default=1920)
    p.add_argument('--height',type=int,default=1080)
    p.add_argument('--port',type=int,default=8766)
    a=p.parse_args()
    import cv2
    cv2.setNumThreads(1)
    from pathlib import Path
    if a.port==8771:
        config=Path('/home/xilinx/posture-s3-20261029/paper-camera-path')
        if config.exists():a.camera=config.read_text().strip()
    device=int(a.camera) if a.camera.isdigit() else a.camera
    cap=cv2.VideoCapture(device,cv2.CAP_V4L2)
    if not cap.isOpened():raise RuntimeError('camera_open_failed')
    if a.port==8771:cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,a.width);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,a.height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
    warmup_until=time.monotonic()+(4 if a.port==8771 else 0)
    lock=threading.Lock();latest={};stop=threading.Event()
    def capture():
        sequence=0
        try:
            while not stop.is_set():
                ok,frame=cap.read()
                if not ok:break
                sequence+=1
                if time.monotonic()<warmup_until:continue
                with lock:
                    latest.update(frame=frame,sequence=sequence,monotonic=time.monotonic(),
                                  utc=datetime.now(timezone.utc).isoformat())
        finally:
            cap.release()
    thread=threading.Thread(target=capture,daemon=True);thread.start()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path!='/snapshot':self.send_error(404);return
            with lock:state=dict(latest)
            if 'frame' not in state or time.monotonic()-state['monotonic']>2:
                self.send_error(503,'camera frame unavailable or stale');return
            ok,data=cv2.imencode('.jpg',state['frame'],[cv2.IMWRITE_JPEG_QUALITY,95])
            if not ok:self.send_error(503,'encode failed');return
            self.send_response(200)
            for k,v in {'Content-Type':'image/jpeg','Content-Length':len(data),
                        'X-Captured-Monotonic':state['monotonic'],'X-Captured-At':state['utc'],
                        'X-Camera-Device':a.camera,'X-Sequence':state['sequence'],
                        'X-Width':state['frame'].shape[1],'X-Height':state['frame'].shape[0]}.items():
                self.send_header(k,str(v))
            self.end_headers();self.wfile.write(data.tobytes())
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    print('CAMERA_SNAPSHOT_READY',a.camera,a.width,a.height,a.port,flush=True)
    try:server.serve_forever()
    finally:stop.set();server.server_close()


if __name__=='__main__':main()
