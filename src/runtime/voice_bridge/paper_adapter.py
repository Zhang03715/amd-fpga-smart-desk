"""Board capture and authenticated PC classification, sharing the known camera owner."""
import json,time,uuid,hashlib,urllib.request
from pathlib import Path
from adapter_control.paper_motors import PaperMotors
from ocr_link.client import OCRClient,make_request,read_token
from ocr_link.snapshot import read_snapshot
from .paper_workflow import PaperWorkflow

def create_paper_workflow(bridge,control,server,token_file,runtime,allow_motion=False):
 root=Path(runtime);root.mkdir(parents=True,exist_ok=True)
 motors=PaperMotors(bridge,allow_motion=allow_motion)
 client=OCRClient(server,read_token(token_file),request_timeout=8,total_timeout=150)
 previous={'mode':'off'}
 def capture(sheet_id):
  mode=control.status().get('camera_mode') or 'off';previous['mode']=mode if mode in ('posture','shelf','off') else 'off'
  control.switch('paper');started=time.monotonic();deadline=started+20
  while True:
   try:
    data,info=read_snapshot('http://127.0.0.1:8771/snapshot')
    if info['captured_monotonic']>started and len(data)<=2*1024*1024:break
   except (OSError,ValueError):pass
   if time.monotonic()>=deadline:raise ValueError('paper_camera_start_timeout')
   time.sleep(.2)
  path=root/'paper-captures'/sheet_id;path.mkdir(parents=True,exist_ok=True);(path/'capture.jpg').write_bytes(data)
  temporary=root/'paper-latest.tmp';temporary.write_bytes(data);temporary.replace(root/'paper-latest.jpg')
  source=dict(kind='camera',live=True,capture_id=sheet_id,captured_at=info['captured_at'],age_seconds=max(0,time.monotonic()-info['captured_monotonic']),clock='client_read_completion')
  preview=control.images.info().get('paper_url','') if control.images else ''
  return data,source,preview
 def classify(image,sheet_id,source,operation=None):
  attempt=uuid.uuid4().hex;request=make_request(image,attempt,'book.scan',None,source);request['action']='paper.classify'
  if operation:request['params']={'operation':operation}
  result=client.run(request,root/'paper-captures'/sheet_id/attempt,download_preview=False)
  if result.get('status')!='succeeded':raise ValueError('paper_classification_failed')
  data=result['result']
  if data.get('request_id')!=attempt or data.get('image_sha256')!=hashlib.sha256(image).hexdigest() or data.get('source')!=source:raise ValueError('paper_result_identity_mismatch')
  return dict(data,sheet_id=sheet_id)
 def restore():
  # Restore only if no other user command has changed the camera meanwhile.
  if control.status().get('camera_mode')=='paper':control.switch(previous['mode'])
 flow=PaperWorkflow(motors,capture,classify,root/'paper-workflow.sqlite3',restore=restore)
 return flow
