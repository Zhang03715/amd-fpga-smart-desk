"""Bounded background probes; USB command handling never waits on the network."""
import json,threading,time,urllib.request,urllib.error
from pathlib import Path

class DeviceHealth:
    def __init__(self,server,token_file,snapshot_url):
        self.server=server;self.token_file=token_file;self.snapshot_url=snapshot_url
        self.stop=threading.Event();self.lock=threading.Lock();self.value={'checking':True}
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    def snapshot(self):
        with self.lock:return dict(self.value)
    def close(self):self.stop.set()
    def loop(self):
        while not self.stop.is_set():
            value={'checked_at':time.time()}
            for role,port in [('shelf_camera','1.3'),('posture_camera','1.1')]:
                value[role]=Path('/dev/v4l/by-path/platform-ci_hdrc.0-usb-0:'+port+':1.0-video-index0').exists()
            try:
                token=Path(self.token_file).read_text().strip()
                request=urllib.request.Request(self.server.rstrip('/')+'/v1/health',headers={'Authorization':'Bearer '+token})
                with urllib.request.urlopen(request,timeout=2) as response:
                    result=json.loads(response.read(4096))
                value['ocr']='ready' if result.get('status')=='ready' else 'unavailable'
            except urllib.error.HTTPError as e:value['ocr']='auth_failed' if e.code in (401,403) else 'unavailable'
            except (OSError,ValueError):value['ocr']='offline'
            try:
                with urllib.request.urlopen(self.snapshot_url,timeout=2) as response:
                    captured=float(response.headers['X-Captured-Monotonic'])
                    value['shelf_stream']=0<=time.monotonic()-captured<=3
                    value['resolution']=response.headers.get('X-Width','?')+'×'+response.headers.get('X-Height','?')
                    response.read(8*1024*1024)
            except (OSError,ValueError,TypeError):value['shelf_stream']=False
            with self.lock:self.value=value
            self.stop.wait(10)
