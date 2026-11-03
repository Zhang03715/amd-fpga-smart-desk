"""Loopback-only classification API; never issues transport or actuator commands."""
import hashlib,json,threading,urllib.request,base64,subprocess,tempfile,sys,os
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .classifier import LocalClassifier,load_profile,profile_digest
PROFILE=Path(__file__).with_name('labels.json')
cache=OrderedDict();lock=threading.Lock()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,data):
        payload=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store');self.end_headers()
        try:self.wfile.write(payload)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        if self.path=='/health':
            try:
                with urllib.request.urlopen('http://127.0.0.1:8769/health',timeout=2) as r:model=json.load(r).get('status')=='ok'
            except Exception:model=False
            return self.reply(200,{'service':'local-paper-classifier','transport_control':False,'model_ready':model})
        if self.path=='/labels':
            profile=load_profile(PROFILE);return self.reply(200,dict(profile,profile_sha256=profile_digest(profile)))
        self.reply(404,{'error':'not_found'})
    def do_POST(self):
        if self.headers.get('Origin') is not None:return self.reply(403,{'error':'native_local_client_required'})
        if self.path not in ('/classify','/labels'):return self.reply(404,{'error':'not_found'})
        if not lock.acquire(blocking=False):return self.reply(429,{'error':'classifier_busy'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 1<=length<=8*1024*1024:raise ValueError('invalid_body_size')
            data=json.loads(self.rfile.read(length))
            if self.path=='/labels':
                candidate=dict(name='用户分类方案',version=1,labels=data.get('labels'))
                temp=PROFILE.with_suffix('.tmp');temp.write_text(json.dumps(candidate,ensure_ascii=False),encoding='utf-8')
                try:load_profile(temp);os.replace(temp,PROFILE)
                finally:
                    if temp.exists():temp.unlink()
                return self.reply(200,dict(candidate,profile_sha256=profile_digest(candidate)))
            rid=data.get('sheet_id');text=data.get('text')
            if 'image_base64' in data:
                raw=base64.b64decode(data['image_base64'],validate=True)
                if len(raw)>5*1024*1024:raise ValueError('image_too_large')
                root=Path(__file__).resolve().parents[1]
                with tempfile.TemporaryDirectory(dir=root/'output') as folder:
                    source=Path(folder)/'input';target=Path(folder)/'ocr.json';source.write_bytes(raw)
                    subprocess.run([str(root/'.venv-gpu/Scripts/python.exe'),str(root/'paper_sorting/image_ocr.py'),str(source),str(target)],cwd=root,check=True,timeout=90,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    text=json.loads(target.read_text(encoding='utf-8'))['text']
            if not isinstance(rid,str) or not 1<=len(rid)<=64 or not isinstance(text,str):raise ValueError('sheet_id_and_text_required')
            identity=hashlib.sha256(text.encode()).hexdigest()
            if rid in cache:
                old,result=cache[rid]
                if old!=identity:return self.reply(409,{'error':'sheet_id_conflict'})
                return self.reply(200,result)
            profile=load_profile(PROFILE)  # Immutable mapping snapshot for this sheet.
            result=dict(sheet_id=rid,**LocalClassifier(profile).classify(text))
            cache[rid]=(identity,result)
            while len(cache)>128:cache.popitem(last=False)
            self.reply(200,result)
        except (ValueError,KeyError,TypeError) as error:self.reply(400,{'error':str(error)})
        except Exception:self.reply(503,{'error':'local_model_unavailable','needs_review':True,'slot':None})
        finally:lock.release()
def main():
    server=ThreadingHTTPServer(('127.0.0.1',8770),Handler);server.daemon_threads=True
    print('LOCAL_PAPER_API http://127.0.0.1:8770',flush=True)
    try:server.serve_forever()
    finally:server.server_close()
if __name__=='__main__':main()
