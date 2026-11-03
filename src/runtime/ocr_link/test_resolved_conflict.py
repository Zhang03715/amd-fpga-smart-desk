import json,unittest,copy
from pathlib import Path
from ocr_link.consensus import BookFrameConsensus
class ResolvedConflictTests(unittest.TestCase):
 def result(self):
  return {'matches':[{'text':'解析几何','ocr_confidence':.9987,'book_box':[500,93,612,679]}], 'decisions':[{'v4_text':'解析几何','recognition_conflict':True,'upright_glyph_review':{'selected':True,'text':'解析几何','confidence':.9987,'attempts':[{'selected':True,'text':'解析几何','confidence':.9996,'corroborating_text':'解析几何','corroborating_confidence':.9987}]}}]}
 def observe(self,result):return BookFrameConsensus('解析几何',max_frames=1,single_frame=True).observe(result,dict(sequence=1,captured_monotonic=1,device='0'))
 def test_resolved_old_conflict_passes(self):self.assertIsNotNone(self.observe(self.result()))
 def test_disagreement_still_rejected(self):
  result=self.result();result['decisions'][0]['upright_glyph_review']['attempts'][0]['corroborating_text']='解析几伺';self.assertIsNone(self.observe(result))
 def test_native_conflict_still_rejected(self):
  result=self.result();result['decisions'][0]['native_review']={'conflict':True};self.assertIsNone(self.observe(result))
 def test_low_confidence_correction_still_rejected(self):
  result=self.result();result['decisions'][0]['upright_glyph_review']['confidence']=.80;self.assertIsNone(self.observe(result))
if __name__=='__main__':unittest.main()
