"""Live NCNN simple-front test on the dedicated Hub posture camera."""
from pathlib import Path
import sys,os,time,json,threading,subprocess,select,uuid,hashlib,urllib.request
import cv2,numpy as np
ROOT=Path('/home/xilinx/amd-desk-v2-20261027');sys.path.insert(0,str(ROOT))
from upper_body import assess_simple,calibrate,eligible_front_candidates
sys.path.insert(0,'/home/xilinx/ocr-hotspot-20261028')
from voice_bridge.posture_reference import calibrate_reference
sys.path.insert(0,'/home/xilinx/z2-posture-int8/board')
from run import letterbox
OUT=Path('/home/xilinx/posture-s3-20261029');OUT.mkdir(exist_ok=True)
CAMERA='/dev/v4l/by-path/platform-ci_hdrc.0-usb-0:1.1:1.0-video-index0';CAMERA_ID='posture-hub1.1'
cv2.setNumThreads(1)
cap=cv2.VideoCapture(CAMERA,cv2.CAP_V4L2);assert cap.isOpened()
cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'));cap.set(cv2.CAP_PROP_FRAME_WIDTH,800);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480);cap.set(cv2.CAP_PROP_FPS,10);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
lock=threading.Lock();stop=threading.Event();latest={}
def capture():
 seq=0
 try:
  while not stop.is_set():
   ok,frame=cap.read()
   if not ok:break
   seq+=1
   with lock:latest.update(frame=frame,sequence=seq,monotonic=time.monotonic(),wall=time.time())
 finally:stop.set();cap.release()
thread=threading.Thread(target=capture,daemon=True);thread.start()
print('POSTURE_CAMERA_READY',CAMERA,flush=True)
worker=subprocess.Popen(['/home/xilinx/z2-posture-int8/bin/z2-pose','--model-dir','/home/xilinx/z2-posture-int8/models','--threads','2'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(OUT/'ncnn.log').open('w'),bufsize=0)
baseline_path=OUT/'baseline.json'
baseline=json.loads(baseline_path.read_text()) if baseline_path.exists() else None
if baseline is not None:
 assert baseline.get('camera_id')==CAMERA_ID and baseline.get('camera_path')==CAMERA,'saved baseline belongs to another camera'
 print('POSTURE_BASELINE_REUSED',flush=True)
samples=[];seen=None;last_hash=None;session=uuid.uuid4().hex
calibration_started=time.monotonic() if baseline is None else None
calibration_error=None
try:
 with (OUT/'samples.jsonl').open('a') as log:
  while True:
   request=OUT/'calibration-request.json'
   if request.exists():
    if baseline_path.exists():
     (OUT/'baseline-before-manual.json').write_text(baseline_path.read_text())
     baseline_path.unlink()
    baseline=None;samples=[];last_hash=None
    calibration_started=time.monotonic();calibration_error=None
    request.unlink()
    print('POSTURE_MANUAL_CALIBRATION_STARTED',flush=True)
   while not stop.is_set():
    with lock:s=dict(latest)
    if s and s['sequence']!=seen:break
    time.sleep(.02)
   if stop.is_set():raise RuntimeError('camera disconnected')
   seen=s['sequence'];frame=s['frame'].copy();inp,scale,px,py=letterbox(frame)
   data=inp.tobytes();offset=0
   while offset<len(data):offset+=os.write(worker.stdin.fileno(),data[offset:])
   if not select.select([worker.stdout],[],[],30)[0]:raise TimeoutError('pose timeout')
   raw=json.loads(worker.stdout.readline());candidates=[[[(x-px)/scale,(y-py)/scale,c] for x,y,c in p['keypoints']] for p in raw['people']]
   size=(frame.shape[1],frame.shape[0]);eligible=eligible_front_candidates(candidates,size);points=candidates[eligible[0]] if len(eligible)==1 else []
   age=time.monotonic()-s['monotonic'];a=assess_simple(points,size,baseline,camera_id=CAMERA_ID,age_seconds=age)
   digest=hashlib.sha256(frame.tobytes()).hexdigest()
   if baseline is None and calibration_started is not None and a['state']=='calibration_needed' and digest!=last_hash:
    samples.append(a['metrics']);samples=samples[-3:]
    if len(samples)==3:
     try:baseline=calibrate_reference(samples,CAMERA_ID)
     except ValueError as e:print('CALIBRATION_RETRY',str(e),flush=True)
     if baseline is not None:
      photo=OUT/'baseline.tmp.jpg'
      if not cv2.imwrite(str(photo),frame):raise OSError('baseline photo save failed')
      photo.replace(OUT/'baseline.jpg')
      baseline['photo']='baseline.jpg'
      baseline.update(created_at=time.time(),camera_path=CAMERA)
      (OUT/'baseline.json').write_text(json.dumps(baseline,indent=2))
      print('POSTURE_CALIBRATED',flush=True)
      calibration_started=None
      a=assess_simple(points,size,baseline,camera_id=CAMERA_ID,age_seconds=age)
   elif baseline is None:samples=[]
   if baseline is None and calibration_started is not None and time.monotonic()-calibration_started>20:
    calibration_error='reference_unstable_retry';calibration_started=None;samples=[]
    backup=OUT/'baseline-before-manual.json'
    if backup.exists():
     baseline=json.loads(backup.read_text());baseline_path.write_text(json.dumps(baseline,indent=2))
   last_hash=digest
   classification='bad' if a['state'] in ('head_down','shoulder_tilt','head_down_and_shoulder_tilt') else 'good' if a['state']=='normal' else 'unknown'
   payload=dict(source='detector',source_kind='camera',session_id=session,frame_id=seen,captured_at=s['wall'],classification=classification,reasons=a.get('reasons',[]))
   delivery=None
   try:
    request=urllib.request.Request('http://127.0.0.1:8767/posture/sample',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=.5) as response:delivery=response.status
   except Exception:delivery='not_connected'
   row=dict(sequence=seen,captured_monotonic=s['monotonic'],age_seconds=age,state=a['state'],assessment=a,inference_ms=raw.get('inference_ms'),eligible=len(eligible),calibration_samples=len(samples),calibration_error=calibration_error,delivery=delivery)
   temp=OUT/'status.tmp';temp.write_text(json.dumps(row));temp.replace(OUT/'status.json')
   log.write(json.dumps(row)+'\n');log.flush();print('POSTURE',json.dumps(row),flush=True)
   for i in (0,5,6):
    if points and points[i][2]>=.65:cv2.circle(frame,(int(points[i][0]),int(points[i][1])),4,(0,255,0),-1)
   cv2.putText(frame,a['state'],(8,25),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,255,255),2)
   cv2.imwrite(str(OUT/'latest.tmp.jpg'),frame)
   (OUT/'latest.tmp.jpg').replace(OUT/'latest.jpg')
finally:
 stop.set();worker.stdin.close();worker.terminate()
 try:worker.wait(timeout=3)
 except subprocess.TimeoutExpired:worker.kill();worker.wait()
