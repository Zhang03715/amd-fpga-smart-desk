import unittest
from .local_book_lights import select_axis,horizontal_mapping


class SelectionTests(unittest.TestCase):
    def test_height_does_not_include_led_above_book(self):
        points=[dict(index=21,xy=[10,5]),dict(index=22,xy=[10,25]),dict(index=29,xy=[10,85])]
        self.assertEqual(select_axis(points,[20,20,40,90],1),[22,29])

    def test_thin_spine_between_horizontal_centres(self):
        points=[dict(index=30,xy=[10,90]),dict(index=31,xy=[30,90])]
        self.assertEqual(select_axis(points,[18,20,22,80],0),[30,31])

    def test_no_unmeasured_led_is_invented(self):
        with self.assertRaises(ValueError):select_axis([],[1,2,3,4],1)

    def test_tilted_mayuan_projects_to_bottom_not_title_x(self):
        points=[dict(index=30,xy=[512,864]),dict(index=31,xy=[641,902]),dict(index=32,xy=[760,901])]
        match=dict(orientation='upright',title_box=[[611,104],[646,101],[666,284],[632,287]],book_box=[587,80,707,900])
        self.assertEqual(select_axis(points,match['book_box'],0),[31])
        weights,audit=horizontal_mapping(points,match)
        self.assertEqual(sorted(weights),[31,32])
        self.assertAlmostEqual(sum(weights.values()),1)
        self.assertGreater(weights[32],weights[31])
        self.assertAlmostEqual(audit['rail_intersection'][0],718,delta=2)

    def test_projection_uses_actual_sloped_rail_and_preserves_flat_book_span(self):
        points=[dict(index=30,xy=[100,800]),dict(index=31,xy=[200,900]),dict(index=32,xy=[300,920])]
        weights,audit=horizontal_mapping(points,dict(orientation='upright',title_box=[[140,100],[160,100],[160,300],[140,300]]))
        self.assertAlmostEqual(audit['rail_intersection'][1],850)
        self.assertEqual(weights,{30:.5,31:.5})
        weights,_=horizontal_mapping(points,dict(orientation='flat',book_box=[90,600,310,700]))
        self.assertEqual(weights,{30:1.,31:1.,32:1.})

    def test_projection_does_not_invent_out_of_view_lamps(self):
        points=[dict(index=30,xy=[100,800]),dict(index=31,xy=[200,900])]
        with self.assertRaisesRegex(ValueError,'outside_measured'):
            horizontal_mapping(points,dict(orientation='upright',title_box=[[290,100],[310,100],[310,300],[290,300]]))

    def test_book_just_outside_first_led_uses_its_half_spacing_end_cell(self):
        points=[dict(index=30,xy=[100,800]),dict(index=31,xy=[200,800])]
        weights,audit=horizontal_mapping(points,dict(orientation='upright',title_box=[[80,100],[100,100],[100,300],[80,300]]))
        self.assertEqual(weights,{30:1.0})
        self.assertEqual(audit['method'],'nearest_measured_endpoint')
        self.assertEqual(audit['distance_to_measured_led'],10.)

    def test_uncertain_flat_edges_do_not_claim_full_book_coverage(self):
        points=[dict(index=i,xy=[100+(i-30)*100,800]) for i in range(30,35)]
        with self.assertRaisesRegex(ValueError,'flat_spine_extent_unconfirmed'):
            horizontal_mapping(points,dict(orientation='flat',book_box=[90,600,510,700],
                title_box=[[190,640],[210,640],[210,660],[190,660]],flat_extent_audit={'status':'end_disagreement'}))

    def test_flat_span_includes_endpoint_cell_without_lighting_entire_rail(self):
        points=[dict(index=i,xy=[100+(i-30)*100,800]) for i in range(30,36)]
        weights,_=horizontal_mapping(points,dict(orientation='flat',book_box=[190,600,440,700]))
        self.assertEqual(sorted(weights),[31,32,33])
        weights,_=horizontal_mapping(points,dict(orientation='flat',book_box=[190,600,460,700]))
        self.assertEqual(sorted(weights),[31,32,33,34])
