from pathlib import Path
import urllib.request,json,hashlib,zipfile
root=Path('.build-tools/android').resolve();records=[]
for item in json.loads((root/'downloads.json').read_text()):
 name=item['url'].rsplit('/',1)[1];dest=root/name
 if not dest.exists() or dest.stat().st_size!=int(item['size']):
  with urllib.request.urlopen(item['url'],timeout=45) as r,dest.open('wb') as f:
   while True:
    b=r.read(1024*1024)
    if not b:break
    f.write(b)
 raw=dest.read_bytes();assert len(raw)==int(item['size']);assert hashlib.sha1(raw).hexdigest()==item['checksum']
 target=root/('platform' if item['package'].startswith('platforms') else 'build-tools');target.mkdir(exist_ok=True)
 with zipfile.ZipFile(dest) as z:
  for entry in z.infolist():assert (target/entry.filename).resolve().is_relative_to(target)
  z.extractall(target)
 records.append(dict(item,sha256=hashlib.sha256(raw).hexdigest()));print('SDK_READY',item['package'],flush=True)
(root/'verified.json').write_text(json.dumps(records,indent=2))
