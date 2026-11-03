import unittest,tempfile
from pathlib import Path
import cv2,numpy as np
from .shelf_calibration import grouped_markers,measure_layout
class Groups(unittest.TestCase):
 def fixture(self):
  return dict(camera='0',image_size=[1920,1080],horizontal=[dict(index=i,xy=[300+(i-30)*100,980]) for i in range(30,44)],vertical=[dict(index=i,xy=[100,900-(29-i)*90]) for i in range(29,20,-1)])
 def encode(self,pixels,ref):
  im=np.zeros((1080,1920,3),np.uint8)
  for axis in ['horizontal','vertical']:
   for p in ref[axis]:
    if pixels[p['index']]!=(0,0,0):cv2.circle(im,tuple(p['xy']),9,(0,0,255),-1)
  return cv2.imencode('.png',im)[1].tobytes()
 def test_complete_fast_pass(self):
  ref=self.fixture();pixels=[(0,0,0)]*60;frames=[]
  class Lights:
   def show(_,channel,p,brightness):pixels[:]=p
  def snap(after):frames.append(1);return self.encode(pixels,ref),dict(device='0')
  with tempfile.TemporaryDirectory() as f:
   c=measure_layout(Lights(),snap,Path(f)/'run',reference=ref)
  self.assertEqual(c['capture_count'],10);self.assertEqual(c['accepted_groups'],8);self.assertEqual(c['missing'],[]);self.assertTrue(all(p==(0,0,0) for p in pixels))
 def test_missing_extra_and_shift_rejected(self):
  ref=self.fixture();black=[(0,0,0)]*60;off=self.encode(black,ref)
  for indices in [[30,34],[30,34,38,42]]:
   p=black.copy()
   for i in indices:p[i]=(255,0,0)
   with self.subTest(indices=indices),self.assertRaises(ValueError):grouped_markers(off,self.encode(p,ref),'horizontal',[30,34,38],ref)
  p=black.copy()
  for i in [30,34,38]:p[i]=(255,0,0)
  shifted=self.fixture()
  for point in shifted['horizontal']:point['xy'][1]-=50
  with self.assertRaises(ValueError):grouped_markers(off,self.encode(p,shifted),'horizontal',[30,34,38],ref)
if __name__=='__main__':unittest.main()
