"""One resident GPU layout model, loopback-only and serial inference."""
import json,os,threading,time,io
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
os.environ['FLAGS_allocator_strategy']='auto_growth'

def main():
 import paddle
 assert paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count()>0,'CUDA required'
 paddle.set_device('gpu:0')
 from paddlex import create_model
 from PIL import Image
 lock=threading.Lock();state={'service':'resident-question-layout','ready':False,'device':'gpu:0','predictions':0,'pid':os.getpid()}
 model=create_model(model_name='PP-DocLayoutV3',model_dir=str(ROOT/'.build-tools/doclayout-v3'),device='gpu:0')
 warmup=ROOT/'output/layout-resident-warmup.png';warmup.parent.mkdir(exist_ok=True)
 Image.new('RGB',(640,800),'white').save(warmup)
 next(iter(model.predict(str(warmup),batch_size=1)))
 state['ready']=True
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def reply(self,code,value):
   raw=json.dumps(value,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
  def do_GET(self):
   self.reply(200,state) if self.path=='/health' else self.reply(404,{'error':'not_found'})
  def do_POST(self):
   if self.path!='/predict':return self.reply(404,{'error':'not_found'})
   if self.headers.get('Origin') is not None:return self.reply(403,{'error':'local_client_required'})
   if not lock.acquire(False):return self.reply(429,{'error':'layout_busy'})
   try:
    size=int(self.headers.get('Content-Length',0))
    if not 0<size<=8192:raise ValueError('invalid_size')
    data=json.loads(self.rfile.read(size));path=Path(data['image']).resolve()
    if ROOT not in path.parents or not path.is_file():raise ValueError('image_outside_workspace')
    with Image.open(path) as im:
     if im.width*im.height>24000000:raise ValueError('image_too_large')
     im.verify()
    started=time.monotonic();result=next(iter(model.predict(str(path),batch_size=1)))
    value=result.json;value=value() if callable(value) else value
    if isinstance(value,str):value=json.loads(value)
    value=value.get('res',value);value.update(device='gpu:0',resident=True,inference_seconds=time.monotonic()-started)
    state['predictions']+=1;self.reply(200,value)
   except Exception as e:self.reply(500,{'error':str(e)[:160]})
   finally:lock.release()
 server=ThreadingHTTPServer(('127.0.0.1',8772),Handler);server.daemon_threads=True
 print('LAYOUT_RESIDENT_READY',flush=True);server.serve_forever()
if __name__=='__main__':main()
