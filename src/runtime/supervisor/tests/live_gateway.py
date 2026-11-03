"""Exercise the paired native host without printing credentials."""
from pathlib import Path
import json,time,urllib.request,urllib.error,uuid
root=Path('C:/Users/DELL/AppData/Local/AmdDeskHub');url=json.loads((root/'running.json').read_text())['url']
def native(op,data):
 req=urllib.request.Request(url+'native/'+op,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=35) as r:return json.load(r)
def api(path,body=None):return native('request',dict(path=path,body=body))
def command(action,params=None):
 payload=dict(client_id=uuid.uuid4().hex,action=action,params=params or {})
 result=api('/api/commands',payload)
 if result.get('request_id'):
  request_id=result['request_id']
  for _ in range(15):
   time.sleep(.4);result=api('/api/results/'+request_id)
   if result.get('status') not in ('pending','accepted'):break
 return result
info=api('/api/info');assert info['gateway']=='ESP32-S3'
payload={'client_id':uuid.uuid4().hex,'action':'audio.status','params':{}}
first=api('/api/commands',payload);assert first['status']=='success' and 'volume' in first['data']
assert api('/api/commands',payload)==first
checks=dict(gateway_info=info,audio_status=first,idempotent_retry=True)
for label,headers,body,expected in [('unauthenticated',{},b'{}',401),('browser_origin',{'Origin':'http://untrusted.invalid'},b'{}',403),('deep_json',{},b'{"a":'*13+b'0'+b'}'*13,400)]:
 try:
  req=urllib.request.Request('http://172.19.71.199:8080/api/commands',data=body,headers=headers)
  urllib.request.urlopen(req,timeout=5);raise AssertionError('unexpected acceptance')
 except urllib.error.HTTPError as e:assert e.code==expected,(label,e.code);checks[label]=e.code
import sys
if '--full' in sys.argv:
 assert info['usb_connected'], 'S3 USB is not connected to Z2'
 for action,params in [('protocol.info',{}),('status',{}),('posture.status',{}),('timer.status',{}),('exam.get',{}),('paper.record.list',{'limit':3}),('wrong_question.list',{'limit':3}),('light.calibration',{'mode':'status'})]:
  result=command(action,params)
  if action=='protocol.info':
   for _ in range(5):
    if result.get('status')=='success':break
    time.sleep(1);result=command(action,params)
  assert result.get('status')=='success',(action,result);checks[action]=result
if '--start-posture' in sys.argv:
 checks['posture.start']=command('posture.config',{'operation':'start'})
 assert checks['posture.start']['status']=='success',checks['posture.start']
 for _ in range(20):
  time.sleep(1);pose=command('posture.status')
  if pose.get('data',{}).get('detector',{}).get('available'):break
 assert pose['data']['detector']['available'],pose
 assert pose['data']['detector']['baseline_saved'],pose
 checks['live_posture']=pose
Path('supervisor/tests/live-gateway-proof.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
print('LIVE_GATEWAY_PASS',json.dumps(checks))
