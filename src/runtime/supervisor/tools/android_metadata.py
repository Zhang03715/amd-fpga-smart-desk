from pathlib import Path
import urllib.request,xml.etree.ElementTree as ET,json
root=Path('.build-tools/android');url='https://dl.google.com/android/repository/repository2-3.xml'
raw=urllib.request.urlopen(url,timeout=40).read();(root/'repository.xml').write_bytes(raw)
tree=ET.fromstring(raw);packages=[]
for p in tree:
 if p.tag.split('}')[-1]!='remotePackage' or p.attrib.get('path') not in ('build-tools;35.0.0','platforms;android-35'):continue
 for archive in p.findall('./archives/archive'):
  host=archive.findtext('host-os')
  if host not in (None,'windows'):continue
  c=archive.find('complete')
  if c is not None:packages.append(dict(package=p.attrib['path'],url='https://dl.google.com/android/repository/'+c.findtext('url'),size=c.findtext('size'),checksum=c.findtext('checksum')))
(root/'downloads.json').write_text(json.dumps(packages,indent=2));print(json.dumps(packages,indent=2))
