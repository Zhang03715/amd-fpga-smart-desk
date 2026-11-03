from copy import deepcopy
import unittest
from spine_geometry_quality import annotate_geometry_quality


def region(group,box):
    x1,y1,x2,y2=box
    return dict(spine_group_id=group,title_box=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]],
                text='kept',ocr_confidence=.99,
                upright_geometry_audit=dict(status='refined',side_fit_count=2,top_cap_supported=True,bottom_cap_supported=True))


class GeometryQualityTests(unittest.TestCase):
    def fixture(self):
        return dict(regions=[region('one',[10,20,20,90]),region('two',[45,20,55,90])],
                    spines=[dict(group_id='one',representative_region_id=0,
                                 spine_polygon=[[0,0],[60,0],[60,110],[0,110]])],audit={})

    def test_cross_book_text_requires_review_without_deleting_evidence(self):
        original=self.fixture()
        frozen=deepcopy(original)
        result=annotate_geometry_quality(original)
        quality=result['spines'][0]['geometry_quality']
        self.assertEqual(quality['intersected_other_region_ids'],[1])
        self.assertFalse(quality['usable_for_full_spine_crop'])
        self.assertEqual(original,frozen)
        self.assertEqual(result['regions'],original['regions'])

    def test_missing_cap_is_not_claimed_as_supported(self):
        original=self.fixture()
        original['regions'][1]['spine_group_id']='one'
        original['regions'][0]['upright_geometry_audit']['top_cap_supported']=False
        quality=annotate_geometry_quality(original)['spines'][0]['geometry_quality']
        self.assertEqual(quality['boundary_evidence']['top'],'unverified')
        self.assertEqual(quality['status'],'review_required')

    def test_legacy_spine_fields_unchanged(self):
        original=self.fixture()
        del original['regions'][0]['upright_geometry_audit']
        self.assertEqual(annotate_geometry_quality(original)['spines'],original['spines'])

    def test_one_fitted_side_is_not_a_verified_full_crop(self):
        original=self.fixture()
        original['regions'][1]['spine_group_id']='one'
        original['regions'][0]['upright_geometry_audit']['side_fit_count']=1
        quality=annotate_geometry_quality(original)['spines'][0]['geometry_quality']
        self.assertIn('side_evidence_incomplete',quality['reasons'])
        self.assertFalse(quality['usable_for_full_spine_crop'])


if __name__=='__main__':
    unittest.main()
