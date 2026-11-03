import tempfile,time,unittest,urllib.request,urllib.error,json
from pathlib import Path
from .posture_images import PostureImages

class ImageTests(unittest.TestCase):
 def test_auth_fixed_paths_and_no_stale_preview(self):
  with tempfile.TemporaryDirectory() as root:
   class Control:
    def __init__(self):self.root=Path(root);self.available=True
    def status(self):return {'available':self.available}
   c=Control();(c.root/'latest.jpg').write_bytes(b'\xff\xd8test');(c.root/'baseline.jpg').write_bytes(b'\xff\xd8saved')
   server=PostureImages(c,0,'127.0.0.1').start()
   base='http://127.0.0.1:'+str(server.server.server_port)
   try:
    with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/preview.jpg')
    self.assertEqual(e.exception.code,401)
    suffix='?token='+server.token
    server.alert={'classification':'bad','red_light_active':True,'updated_monotonic':time.monotonic()}
    with urllib.request.urlopen(base+'/status'+suffix) as r:
     self.assertEqual(r.headers['Access-Control-Allow-Origin'],'*')
     self.assertTrue(json.load(r)['red_light_active'])
    server.alert['updated_monotonic']-=10
    with urllib.request.urlopen(base+'/status'+suffix) as r:
     value=json.load(r);self.assertTrue(value['stale']);self.assertIsNone(value['red_light_active'])
    with urllib.request.urlopen(base+'/preview.jpg'+suffix) as r:self.assertEqual(r.read(),b'\xff\xd8test')
    c.available=False
    with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/preview.jpg'+suffix)
    self.assertEqual(e.exception.code,503)
    with urllib.request.urlopen(base+'/baseline.jpg'+suffix) as r:self.assertEqual(r.read(),b'\xff\xd8saved')
    with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/../baseline.json'+suffix)
    self.assertEqual(e.exception.code,404)
   finally:server.close()
