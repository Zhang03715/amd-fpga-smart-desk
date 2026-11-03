"""Local contract fixture only. Never represents connected hardware."""
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  if self.path=='/api/info':result={'gateway':'TEST FIXTURE','api_version':1}
  elif self.path.startswith('/api/results/') and self.headers.get('Authorization')=='Bearer TEST_TOKEN':result={'status':'success','data':{'test_fixture':True}}
  else:self.send_error(401);return
  self.send(result)
 def do_POST(self):
  d=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  if self.path=='/api/pair':
   if d!={'code':'123456'}:self.send_error(403);return
   result={'token':'TEST_TOKEN'}
  elif self.path=='/api/commands' and self.headers.get('Authorization')=='Bearer TEST_TOKEN':
   if d['action']=='timer.start':assert d['params']=={'minutes':25},d
   if d['action']=='posture.config':assert d['params']=={'duration':10,'cooldown':60},d
   if d['action']=='book.find':assert d['params']=={'title':'大学物理学'},d
   with Path('supervisor/tests/requests.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(d,ensure_ascii=False)+'\n')
   result={'status':'pending','request_id':d['client_id']}
  else:self.send_error(401);return
  self.send(result)
 def send(self,d):
  data=json.dumps(d).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
HTTPServer(('127.0.0.1',18080),Handler).serve_forever()
