import json,urllib.request,hashlib,time
from pathlib import Path
repo='PaddlePaddle/PP-DocLayoutV3'
with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true',timeout=30) as r:info=json.load(r)
folder=Path('.build-tools/doclayout-v3');folder.mkdir(parents=True,exist_ok=True);manifest={'repo':repo,'revision':info['sha'],'files':{}}
for item in info['siblings']:
 name=item['rfilename']
 if name not in ('inference.json','inference.pdiparams','inference.yml'):continue
 target=folder/name;expected=item.get('lfs',{}).get('sha256');size=item.get('size') or item.get('lfs',{}).get('size')
 if not target.exists() or target.stat().st_size!=size:
  part=target.with_suffix(target.suffix+'.part');request=urllib.request.Request('https://huggingface.co/'+repo+'/resolve/'+info['sha']+'/'+name)
  with urllib.request.urlopen(request,timeout=90) as source,part.open('wb') as out:
   while True:
    b=source.read(1024*1024)
    if not b:break
    out.write(b)
  assert part.stat().st_size==size,(name,part.stat().st_size,size)
  part.replace(target)
 digest=hashlib.sha256(target.read_bytes()).hexdigest()
 if expected:assert digest==expected,name
 manifest['files'][name]={'sha256':digest,'size':target.stat().st_size,'upstream_sha256_checked':bool(expected)};print('MODEL_FILE_VERIFIED',name,target.stat().st_size,flush=True)
(folder/'download-manifest.json').write_text(json.dumps(manifest,indent=2));print('MODEL_READY',info['sha'],flush=True)
