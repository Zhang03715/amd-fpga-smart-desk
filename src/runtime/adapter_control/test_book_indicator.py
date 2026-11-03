import unittest
from .run import AdapterService
from .test_spine_lights import MappingTests


class Light:
    def __init__(self):self.frames=[]
    def show(self,channel,pixels,brightness=.1):self.frames.append((channel,list(pixels),brightness))


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.now=0;self.light=Light()
        self.s=AdapterService(lights=self.light,counts=(1,30),active_counts=(0,15),
                              spine_mapper=MappingTests().mapper(),clock=lambda:self.now)
        self.s.book_view=dict(state='found',request_id='job1',completed_at=0,indicator_lit=False,
                             result=dict(found=True,image_size=[200,100],matches=[dict(book_box=[14,10,16,90])],
                                         geometry_quality_evaluated=True,geometry_review_required_count=0,
                                         source=dict(kind='camera',live=True,camera_id='2',age_at_result_seconds=1)))
    def tearDown(self):self.s.close()
    def test_between_leds_and_cancel_clears_all_30(self):
        r=self.s.execute('book.indicate',dict(request_id='job1'))
        self.assertEqual(r['led_indices'],[0,1]);self.assertEqual(len(self.light.frames[-1][1]),30)
        self.assertTrue(all(x==(0,0,0) for x in self.light.frames[-1][1][15:]))
        self.s.execute('book.cancel',{})
        self.assertTrue(all(x==(0,0,0) for x in self.light.frames[-1][1]))
    def test_stale_offline_wrong_job_and_unverified_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'current'):self.s.execute('book.indicate',dict(request_id='other'))
        self.s.book_view['result']['source']['live']=False
        with self.assertRaisesRegex(ValueError,'fresh'):self.s.execute('book.indicate',dict(request_id='job1'))
        self.s.book_view['result']['source']['live']=True
        self.s.book_view['result']['geometry_review_required_count']=1
        with self.assertRaisesRegex(ValueError,'unverified'):self.s.execute('book.indicate',dict(request_id='job1'))
        self.assertEqual(self.light.frames,[])
    def test_expiry_turns_off_indicator_and_scene_masks_tail(self):
        self.s.execute('book.indicate',dict(request_id='job1'));self.now=31;self.s.update_book_view()
        self.assertEqual(self.s.book_view['state'],'expired')
        self.assertTrue(all(x==(0,0,0) for x in self.light.frames[-1][1]))
        self.s.execute('light.scene',dict(scene='focus'))
        self.assertTrue(all(x==(0,0,0) for x in self.light.frames[-1][1][15:]))
