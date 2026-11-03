import copy,json,tempfile,unittest
from pathlib import Path
from .classifier import load_profile,validate_result,LocalClassifier,profile_digest
PROFILE=load_profile(Path(__file__).with_name('labels.json'))
class ClassifierTests(unittest.TestCase):
 def test_mapping_is_owned_by_program_not_model(self):
  value=dict(label_id='physics',needs_review=False,evidence=['电阻测量'],reason='本页为物理实验。',slot=3)
  result=validate_result(value,'电阻测量实验记录',PROFILE)
  self.assertEqual(result['slot'],2);self.assertFalse(result['dispatch_ready'])
 def test_review_has_no_destination(self):
  r=validate_result(dict(label_id='math',needs_review=True,evidence=['积分'],reason='同时涉及多个类别。'),'积分与电场实验',PROFILE)
  self.assertIsNone(r['slot']);self.assertEqual(r['label_id'],'REVIEW')
 def test_invented_evidence_and_unknown_labels_fail(self):
  for value in [dict(label_id='math',needs_review=False,evidence=['不存在的文字'],reason='测试'),dict(label_id='slot_4',needs_review=False,evidence=['积分'],reason='测试')]:
   with self.assertRaises(ValueError):validate_result(value,'积分与导数',PROFILE)
 def test_blank_never_calls_model(self):
  r=LocalClassifier(PROFILE).classify('  ');self.assertEqual(r['classifier'],'quality_gate');self.assertIsNone(r['slot'])
 def test_profile_change_changes_fingerprint(self):
  changed=copy.deepcopy(PROFILE);changed['labels'][0]['name']='其他数学资料';self.assertNotEqual(profile_digest(changed),profile_digest(PROFILE))
 def test_remote_model_endpoint_refused(self):
  with self.assertRaises(ValueError):LocalClassifier(PROFILE,'https://example.com/classify')
 def test_invalid_slot_profile_rejected(self):
  changed=copy.deepcopy(PROFILE);changed['labels'][0]['slot']=True
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'labels.json';p.write_text(json.dumps(changed))
   with self.assertRaises(ValueError):load_profile(p)
if __name__=='__main__':unittest.main()
