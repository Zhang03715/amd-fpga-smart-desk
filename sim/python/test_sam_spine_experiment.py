import unittest
import numpy as np
from sam_spine_experiment import validate_mask,prompt_points,prompt_box,contour_quad,mask_side_quad,full_axis_prompt_box,prior_axis_points,propose_spines


class SAMProposalTests(unittest.TestCase):
    def test_explicit_supported_quad_keeps_cap_and_checks_neighbour_text(self):
        quad=np.asarray([[20,10],[69,10],[69,159],[20,159]],np.float32)
        selected,audit=validate_mask(self.mask,self.points,self.labels,self.title,proposed_quad=quad)
        self.assertIsNotNone(selected)
        np.testing.assert_array_equal(audit['polygon'],quad.astype(int))
        selected,audit=validate_mask(self.mask,self.points,self.labels,self.title,
            excluded_title_boxes=[[[60,45],[78,45],[78,90],[60,90]]],proposed_quad=quad)
        self.assertIsNone(selected)
        self.assertEqual(audit['reason'],'includes_neighbour_text')

    def test_explicit_quad_cannot_expand_beyond_mask_support(self):
        selected,audit=validate_mask(self.mask,self.points,self.labels,self.title,
            proposed_quad=[[0,0],[79,0],[79,179],[0,179]])
        self.assertIsNone(selected)
        self.assertEqual(audit['reason'],'proposed_quad_not_supported_by_mask')

    def test_filtering_inference_negative_does_not_remove_validation_guard(self):
        from unittest.mock import patch
        calls=[]
        mask=self.mask.copy();mask[10:160,20:130]=True
        class Predictor:
            def set_image(self,image):
                pass
            def predict(self,**kwargs):
                calls.append(kwargs)
                return np.asarray([mask]),np.asarray([.99]),None
        grouped={'audit':{},'regions':[{'title_box':self.title},
                 {'title_box':[[90,35],[110,35],[110,115],[90,115]]}],
                 'spines':[{'group_id':str(i),'region_ids':[i],'representative_region_id':i,
                            'book_box':[20,0,130,179],
                            'spine_polygon':[[20,0],[130,0],[130,179],[20,179]]} for i in range(2)]}
        with patch('spine_prompt_relations_experiment.text_band_relation',return_value={'relation':'unknown'}):
            _,proposals,masks,_=propose_spines(np.zeros((*mask.shape,3),np.uint8),grouped,Predictor(),evidence_negative_prompts=True)
        self.assertFalse(masks)
        self.assertTrue(all(call['point_labels'] is None or np.all(call['point_labels']==1) for call in calls))
        self.assertTrue(all(c['reason']=='includes_neighbour_seed' for p in proposals for c in p['candidates']))

    def test_high_model_score_cannot_ignore_new_axis_anchor(self):
        mask=self.mask.copy()
        class Predictor:
            def set_image(self,image):
                pass
            def predict(self,**kwargs):
                labels=kwargs.get('point_labels')
                score=1. if labels is not None and len(labels)>3 else .8
                return np.asarray([mask]),np.asarray([score]),None
        grouped={'audit':{},'regions':[{'title_box':self.title}],
                 'spines':[{'group_id':'one','region_ids':[0],'representative_region_id':0,
                            'book_box':[20,0,70,179],
                            'spine_polygon':[[20,0],[70,0],[70,179],[20,179]]}]}
        _,proposals,_,_=propose_spines(np.zeros((*mask.shape,3),np.uint8),grouped,Predictor(),prior_axis_prompts=True)
        self.assertNotIn(proposals[0]['selected']['prompt_mode'],('prior_axis_points','full_axis_points'))
        for candidate in proposals[0]['candidates']:
            if candidate['prompt_mode'] in ('prior_axis_points','full_axis_points'):
                self.assertFalse(candidate['eligible'])
                self.assertEqual(candidate['reason'],'positive_seeds_disconnected')

    def test_prior_axis_anchors_extend_beyond_title_inside_flat_prior(self):
        spine={'spine_polygon':[[10,20],[150,20],[150,60],[10,60]]}
        anchors=prior_axis_points(spine,(180,200,3))
        np.testing.assert_allclose(np.sort(anchors[:,0]),[24,136])
        np.testing.assert_allclose(anchors[:,1],[40,40])

    def test_prior_axis_anchors_are_clipped_to_frame(self):
        spine={'spine_polygon':[[-20,20],[220,20],[220,60],[-20,60]]}
        anchors=prior_axis_points(spine,(100,100,3))
        self.assertTrue(np.all(anchors>=0))
        self.assertTrue(np.all(anchors<=99))

    def test_full_extent_anchors_are_not_limited_by_short_prior(self):
        spine={'spine_polygon':[[10,20],[150,20],[150,60],[10,60]]}
        anchors=prior_axis_points(spine,(180,200,3),full_extent=True)
        np.testing.assert_allclose(np.sort(anchors[:,0]),[19.9,179.1],atol=1e-4)
        np.testing.assert_allclose(anchors[:,1],[40,40])

    def test_full_axis_prompt_preserves_upright_neighbour_corridor(self):
        box=np.asarray([20,30,70,140],np.float32)
        actual=full_axis_prompt_box(box,[[30,40],[50,40],[50,110],[30,110]],(180,200,3))
        self.assertEqual(actual.tolist(),[20,0,70,179])
        self.assertEqual(box.tolist(),[20,30,70,140])

    def test_full_axis_prompt_handles_flat_titles(self):
        actual=full_axis_prompt_box([30,20,140,70],[[40,30],[110,30],[110,50],[40,50]],(180,200,3))
        self.assertEqual(actual.tolist(),[0,20,199,70])

    def test_full_axis_prompt_does_not_expand_diagonal_title(self):
        box=[20,30,170,150]
        actual=full_axis_prompt_box(box,[[30,30],[40,20],[140,120],[130,130]],(180,200,3))
        self.assertEqual(actual.tolist(),box)

    def test_side_fit_rejects_empty_mask(self):
        self.assertIsNone(mask_side_quad(np.zeros((180,200),bool)))

    def test_side_fit_preserves_tapered_mask(self):
        import cv2
        mask=np.zeros((220,180),np.uint8)
        cv2.fillConvexPoly(mask,np.asarray([[55,10],[100,10],[120,200],[30,200]]),1)
        quad=mask_side_quad(mask.astype(bool))
        self.assertIsNotNone(quad)
        raster=np.zeros_like(mask)
        cv2.fillConvexPoly(raster,np.rint(quad).astype(np.int32),1)
        self.assertGreater(np.count_nonzero(mask&raster)/np.count_nonzero(mask|raster),.90)

    def test_trapezoid_keeps_nonparallel_sides(self):
        contour=np.asarray([[[20,10]],[[65,14]],[[78,160]],[[10,150]]],np.int32)
        quad,method=contour_quad(contour)
        self.assertEqual(method,'convex_contour_quad')
        self.assertEqual(set(map(tuple,quad.tolist())),set(map(tuple,contour.reshape(4,2).tolist())))

    def setUp(self):
        self.mask=np.zeros((180,200),bool)
        self.mask[10:160,20:70]=True
        self.points=np.asarray([[40,40],[40,70],[40,110],[100,70]],float)
        self.labels=np.asarray([1,1,1,0])
        self.title=[[32,35],[48,35],[48,115],[32,115]]

    def test_negative_neighbour_prevents_two_books_from_becoming_one(self):
        mask=self.mask.copy();mask[10:160,20:130]=True
        selected,audit=validate_mask(mask,self.points,self.labels,self.title)
        self.assertIsNone(selected)
        self.assertEqual(audit['reason'],'includes_neighbour_seed')

    def test_disconnected_mask_is_not_unioned_across_neighbour(self):
        mask=self.mask.copy();mask[10:160,90:130]=True
        selected,audit=validate_mask(mask,self.points,self.labels,self.title)
        self.assertTrue(audit['eligible'])
        self.assertFalse(selected[70,100])
        self.assertEqual(audit['book_box'],[20,10,69,159])

    def test_single_negative_hole_cannot_hide_a_cross_book_mask(self):
        mask=np.zeros_like(self.mask);mask[20:130,20:120]=True
        mask[65:76,95:106]=False
        selected,audit=validate_mask(mask,self.points,self.labels,self.title,
                                    [[[90,35],[110,35],[110,115],[90,115]]])
        self.assertIsNone(selected)
        self.assertEqual(audit['reason'],'includes_neighbour_text')

    def test_quad_cannot_bridge_notch_over_neighbour_text_edge(self):
        mask=np.zeros_like(self.mask)
        mask[10:160,20:80]=True
        mask[60:101,69:80]=False
        selected,audit=validate_mask(mask,self.points,self.labels,self.title,
                                    [[[70,65],[90,65],[90,95],[70,95]]])
        self.assertIsNone(selected)
        self.assertEqual(audit['reason'],'fitted_quad_overlaps_neighbour_text')
        self.assertGreater(audit['neighbour_text_overlap'],.15)

    def test_notch_with_neighbour_outside_fitted_quad_remains_valid(self):
        mask=np.zeros_like(self.mask)
        mask[10:160,20:80]=True
        mask[60:101,69:80]=False
        selected,audit=validate_mask(mask,self.points,self.labels,self.title,
                                    [[[84,65],[104,65],[104,95],[84,95]]])
        self.assertIsNotNone(selected)
        self.assertTrue(audit['eligible'])

    def test_refined_cap_box_tracks_quad_and_retains_original_mask_box(self):
        from unittest.mock import patch
        quad=np.asarray([[20,25],[69,25],[69,159],[20,159]],np.float32)
        image=np.zeros((*self.mask.shape,3),np.uint8)
        with patch('spine_cap_edges.refine_supported_caps',return_value=(quad,{'applied':True})):
            selected,audit=validate_mask(self.mask,self.points,self.labels,self.title,image=image,edge_caps=True)
        self.assertIsNotNone(selected)
        self.assertEqual(audit['book_box'],[20,25,69,159])
        self.assertEqual(audit['mask_box'],[20,10,69,159])

    def test_prompt_uses_evidence_not_transcription_or_catalogue(self):
        rows=[dict(title_box=self.title),dict(title_box=[[90,35],[110,35],[110,115],[90,115]])]
        groups=[dict(group_id='one',region_ids=[0],representative_region_id=0),dict(group_id='two',region_ids=[1],representative_region_id=1)]
        points,labels=prompt_points(groups[0],rows,groups)
        self.assertEqual(labels.tolist(),[1,1,1,0])
        self.assertEqual(points[-1].tolist(),[100,75])

    def test_partial_book_missing_member_text_is_rejected(self):
        selected,audit=validate_mask(self.mask,self.points,self.labels,self.title,
            member_title_boxes=[[[30,165],[50,165],[50,175],[30,175]]])
        self.assertIsNone(selected)
        self.assertEqual(audit['reason'],'misses_group_member_text')

    def test_sparse_title_fragment_is_not_a_book_mask(self):
        mask=self.mask.copy()
        mask[15:155,21:32]=False
        mask[15:155,49:69]=False
        selected,audit=validate_mask(mask,self.points,self.labels,self.title)
        self.assertIsNone(selected)
        self.assertEqual(audit['reason'],'sparse_text_fragment')

    def test_neighbour_text_limits_wide_prior_prompt_not_output_mask(self):
        rows=[dict(title_box=self.title),dict(title_box=[[90,35],[110,35],[110,115],[90,115]])]
        groups=[dict(group_id='one',representative_region_id=0,
                     spine_polygon=[[0,0],[130,0],[130,170],[0,170]]),
                dict(group_id='two',representative_region_id=1)]
        box=prompt_box(groups[0],rows,groups,(180,200,3))
        self.assertLess(box[2],100)
        self.assertGreaterEqual(box[2],48)


if __name__=='__main__':
    unittest.main()
