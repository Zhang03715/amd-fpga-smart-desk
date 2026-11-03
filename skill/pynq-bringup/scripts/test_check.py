import unittest,tempfile,json,hashlib
from pathlib import Path
from check import subset,verify_manifest,verify_timing
class Checks(unittest.TestCase):
 def test_subset(self):
  subset({'state':'ready'},{'state':'ready','extra':1})
  with self.assertRaises(ValueError):subset({'ok':True},{'ok':1})
  with self.assertRaises(ValueError):subset({'state':'ready'},{'state':'failed'})
 def test_manifest(self):
  with tempfile.TemporaryDirectory(prefix='pynq skill ') as f:
   p=Path(f);(p/'artifact.bin').write_bytes(b'demo');m=p/'manifest.json'
   m.write_text(json.dumps({'artifact.bin':hashlib.sha256(b'demo').hexdigest()}));self.assertEqual(verify_manifest(m),1)
   (p/'artifact.bin').write_bytes(b'changed')
   with self.assertRaises(ValueError):verify_manifest(m)
   m.write_text(json.dumps({'../escape':'0'*64}))
   with self.assertRaises(ValueError):verify_manifest(m)
   m.write_text(json.dumps({'missing':'0'*64}))
   with self.assertRaises(ValueError):verify_manifest(m)
 def test_timing(self):
  d=dict(wns_ns=.1,whs_ns=.01,drc_errors=0,unconstrained_paths=0,resource_usage={'LUT':20},resource_limits={'LUT':30})
  with tempfile.TemporaryDirectory() as f:
   p=Path(f)/'timing.json';p.write_text(json.dumps(d));verify_timing(p)
   for key,value in [('wns_ns',-.1),('whs_ns',float('nan')),('drc_errors',1),('unconstrained_paths',1),('resource_usage',{'LUT':31})]:
    bad=dict(d);bad[key]=value;p.write_text(json.dumps(bad))
    with self.subTest(key=key),self.assertRaises(ValueError):verify_timing(p)
if __name__=='__main__':unittest.main()
