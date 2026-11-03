"""One LCD writer sharing the existing Bridge object with LED2, no second overlay."""
import copy,io,json,threading,time
from collections import deque
from pathlib import Path
from queue import Queue,Empty,Full
from .dashboard import Dashboard,find_font
from .lcd import ST7789
from .menu import Buttons

class LCDDashboard:
    def __init__(self,bridge,runtime,font=None,native=True):
        import fcntl
        self.owner=Path('/tmp/amd-lcd-owner.lock').open('a')
        fcntl.flock(self.owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.bridge=bridge;self.runtime=Path(runtime);self.runtime.mkdir(parents=True,exist_ok=True)
        self.menu=Dashboard(font or find_font());self.native=native
        self.stop=threading.Event();self.lock=threading.Lock();self.snapshot={};self.commands=Queue(maxsize=8)
        self.status={'state':'starting'};self.last_publish=0
        self.thread=threading.Thread(target=self.loop,name='lcd-dashboard',daemon=True)
    def start(self):self.thread.start();return self
    def publish(self,snapshot):
        with self.lock:self.snapshot=copy.deepcopy(snapshot);self.last_publish=time.monotonic()
    def close(self):
        self.stop.set();self.thread.join(timeout=5)
        if not self.thread.is_alive():self.owner.close()
    def drain(self,service):
        while True:
            try:action,params=self.commands.get_nowait()
            except Empty:return
            try:
                service.execute(action,params)
                self.menu.message='已提交，请等待状态更新'
            except (OSError,ValueError):self.menu.message='任务忙或设备未就绪'
    def report(self,**values):
        self.status.update(values)
        path=self.runtime/'lcd-status.json';temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.status));temp.replace(path)
    def preview(self,snapshot):
        from PIL import Image
        detector=snapshot.get('pose',{}).get('detector',{})
        if detector.get('camera_mode')=='posture':
            path=self.runtime/'latest.jpg'
            if time.time()-path.stat().st_mtime<=3:
                with Image.open(path) as image:return image.convert('RGB')
        if detector.get('camera_mode') in ('shelf','paper'):
            import urllib.request
            port=8771 if detector.get('camera_mode')=='paper' else 8766
            with urllib.request.urlopen('http://127.0.0.1:%d/snapshot'%port,timeout=.4) as response:
                captured=float(response.headers['X-Captured-Monotonic'])
                if 0<=time.monotonic()-captured<=3:
                    with Image.open(io.BytesIO(response.read(2*1024*1024))) as image:return image.convert('RGB')
        return None
    def scan_buttons(self, keys, finished):
        buttons=Buttons()
        while not self.stop.is_set() and not finished.is_set():
            try:
                for key in buttons.update(self.bridge.buttons()):
                    try:keys.put_nowait(key)
                    except Full:self.status['key_queue_full']=self.status.get('key_queue_full',0)+1
                    else:
                        self.status['keys_read']=self.status.get('keys_read',0)+1
                        self.status['last_key']=key
                self.status.pop('key_scan_error',None)
            except (OSError,RuntimeError) as error:
                self.status['key_scan_error']=type(error).__name__
            finished.wait(.01)
    def loop(self):
        keys=Queue(maxsize=64);finished=threading.Event()
        scanner=threading.Thread(target=self.scan_buttons,args=(keys,finished),name='lcd-keys',daemon=True)
        scanner.start()
        try:self.display_loop(keys)
        finally:
            finished.set();scanner.join(timeout=2)
    def display_loop(self,keys):
        attempt=0;next_render=0;last_report=0
        while not self.stop.is_set() and attempt<3:
            try:
                if self.native:
                    from .native_lcd import enable
                    enable(self.bridge)
                lcd=ST7789(self.bridge,dirty_band_height=16)
                # Reinitialize the panel only; never reload PL or reset the LED driver.
                lcd.initialize();self.report(state='ready',native=self.native,font=bool(self.menu.font),error=None)
                while not self.stop.is_set():
                    with self.lock:snapshot=copy.deepcopy(self.snapshot);age=time.monotonic()-self.last_publish
                    snapshot['stale']=age>3
                    while True:
                        try:key=keys.get_nowait()
                        except Empty:break
                        command=self.menu.key(key,snapshot);next_render=0
                        if command:
                            try:self.commands.put_nowait(command)
                            except Full:self.menu.message='请稍后重试'
                    if time.monotonic()>=next_render:
                        preview=None
                        if self.menu.page=='preview':
                            try:preview=self.preview(snapshot)
                            except (OSError,ValueError,KeyError,TypeError):pass
                        started=time.monotonic();sent=lcd.show(self.menu.render(snapshot,preview))
                        self.status.update(page=self.menu.page,bytes_sent=sent,render_ms=round((time.monotonic()-started)*1000,1))
                        next_render=time.monotonic()+(1 if self.menu.page=='preview' else .5)
                        if time.monotonic()-last_report>5:self.report(state='ready');last_report=time.monotonic()
                    self.stop.wait(.03)
            except Exception as error:
                attempt+=1
                try:self.report(state='retrying' if attempt<3 else 'failed',error=type(error).__name__,attempt=attempt)
                except OSError:pass
                self.stop.wait(2)

def lcd_snapshot(service,s3=False):
    pose=service.execute('posture.status',{}) if service.posture_control is not None else {}
    book={'state':'idle'}
    book_jobs=[(rid,job) for rid,job in service.jobs.items() if job.get('kind')!='paper']
    if book_jobs:
        rid,job=book_jobs[-1];result=job['result'];data=result.get('data',{})
        kind=job.get('kind')
        book=dict(state=('calibrating' if kind=='calibration' else 'searching') if job['future'] is not None else
                  'failed' if result['status']!='success' else 'idle' if kind=='calibration' else 'found' if data.get('found') else 'not_found',
                  title=job.get('title',''),indicator_lit=bool(data.get('indicator_lit')),error=result.get('error'))
    return dict(paper=service.execute('paper.status',{}),pose=pose,book=book,s3=s3,timer=service.timer_status(),exam=service.features.execute('exam.get',{}),courses=service.features.execute('timetable.get',{}),records=service.features.execute('paper.record.list',{'limit':3,'offset':0})['records'],wrong_records=service.features.execute('wrong_question.list',{'limit':3,'offset':0})['records'],
                health=service.health.snapshot() if service.health else {},
                calibrated=bool(getattr(service.book_adapter,'calibration_valid',False)))
