"""File-based control of the existing live pose process; no camera ownership."""
import json,time,uuid,subprocess,os,signal
from pathlib import Path

def atomic_owner_write(path,text):
    temporary=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    try:
        with temporary.open('w',encoding='utf-8') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()

class PostureControl:
    def __init__(self,root,clock=time.time,runner=None,paper_camera='1'):
        self.root=Path(root);self.clock=clock;self.runner=Path(runner) if runner else None
        self.process=None
        self.images=None
        self.paper_camera=str(paper_camera)
    def prepare_shelf(self):
        """Wait for actual frames before OCR, including voice-triggered requests."""
        import urllib.request
        owner=self.root/'camera-owner.json'
        try:mode=json.loads(owner.read_text()).get('mode') if owner.exists() else None
        except (OSError,ValueError):mode='unknown'
        if mode!='shelf':self.switch('shelf')
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8766/snapshot',timeout=2) as response:
                    if response.status==200 and len(response.read(8*1024*1024))>100:return
            except (OSError,ValueError):pass
            time.sleep(.3)
        raise ValueError('shelf_camera_start_timeout')
    def start(self):
        if self.status()['available']:return {'running':True,'already_running':True}
        if self.runner is None or not self.runner.is_file():raise ValueError('posture_runner_not_configured')
        return self.switch('posture')
    def switch(self,mode):
        if mode not in ('posture','shelf','paper','off'):raise ValueError('invalid_camera_mode')
        if self.runner is None or not self.runner.is_file():raise ValueError('posture_runner_not_configured')
        self.root.mkdir(parents=True,exist_ok=True)
        owner=self.root/'camera-owner.json'
        if owner.exists():
            old=json.loads(owner.read_text());pid=old.get('pid',0);proc=Path('/proc')/str(pid)
            if type(pid) is int and pid>1 and proc.exists() and old.get('boot_id')==Path('/proc/sys/kernel/random/boot_id').read_text():
                # PID reuse must never terminate an unrelated process group.
                ticks=(proc/'stat').read_text().rsplit(')',1)[1].split()[19]
                if old.get('start_ticks')==ticks and os.getpgid(pid)==pid:
                    try:os.killpg(pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                    for _ in range(20):
                        if self.process is not None:self.process.poll()
                        if not proc.exists():break
                        time.sleep(.05)
            owner.unlink()
        if mode=='off':
            atomic_owner_write(owner,json.dumps({'mode':'off'}));return {'mode':'off','stopped':True}
        python='/usr/local/share/pynq-venv/bin/python3'
        if mode=='posture':
            args=['sg','video','-c','OMP_WAIT_POLICY=PASSIVE '+python+' -u '+str(self.runner)]
            if os.geteuid()==0:args=['sudo','-u','xilinx']+args
        else:args=[python,'-u','-m','ocr_link.camera_daemon','--camera',self.paper_camera if mode=='paper' else '0','--width','1920','--height','1080','--port','8771' if mode=='paper' else '8766']
        with (self.root/('live.log' if mode=='posture' else 'shelf-camera.log')).open('w') as output:
            self.process=subprocess.Popen(args,cwd='/home/xilinx/ocr-hotspot-20261028',stdout=output,stderr=output,stdin=subprocess.DEVNULL,start_new_session=True)
        proc=Path('/proc')/str(self.process.pid)
        atomic_owner_write(owner,json.dumps(dict(pid=self.process.pid,mode=mode,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text(),start_ticks=(proc/'stat').read_text().rsplit(')',1)[1].split()[19])))
        (self.root/'live.pid').write_text(str(self.process.pid))
        return {'queued':True,'running':False,'mode':mode,'message':'相机切换已提交，请等待有效画面；保存的标定未改变。'}
    def status(self):
        path=self.root/'status.json'
        try:
            state=json.loads(path.read_text())
            age=max(0,self.clock()-path.stat().st_mtime)
        except (OSError,ValueError):return {'available':False,'state':'unknown','baseline_saved':(self.root/'baseline.json').exists()}
        fresh=age<=8
        owner=self.root/'camera-owner.json'
        try:mode=json.loads(owner.read_text()).get('mode') if owner.exists() else None
        except (OSError,ValueError):mode='unknown'
        if mode not in (None,'posture'):fresh=False
        try:baseline=json.loads((self.root/'baseline.json').read_text())
        except (OSError,ValueError):baseline={}
        return {'available':fresh,'state':state.get('state','unknown') if fresh else 'unknown',
                'reasons':state.get('assessment',{}).get('reasons',[]) if fresh else [],
                'images':self.images.info() if self.images else {},
                'baseline_photo_saved':bool(baseline.get('photo') and (self.root/'baseline.jpg').exists()),
                'baseline_created_at':baseline.get('created_at'),
                'camera_mode':mode,
                'age_seconds':round(age,2),'inference_ms':state.get('inference_ms'),
                'calibration_samples':state.get('calibration_samples',0),
                'calibration_error':state.get('calibration_error') if fresh else None,
                'baseline_saved':(self.root/'baseline.json').exists(),
                'calibration_pending':(self.root/'calibration-request.json').exists() or state.get('state')=='calibration_needed'}
    def calibrate(self):
        if not self.status()['available']:raise ValueError('posture_detector_not_running')
        path=self.root/'calibration-request.json'
        if path.exists():raise ValueError('posture_calibration_pending')
        request={'id':uuid.uuid4().hex,'created_at':self.clock()}
        # Exclusive creation avoids replacing an unread calibration request.
        with path.open('x') as f:json.dump(request,f)
        return {'queued':True,'completed':False,'message':'请自然坐直并保持脸和双肩完整入画；采集最多等待20秒，完成后保存一张正坐照片。'}
