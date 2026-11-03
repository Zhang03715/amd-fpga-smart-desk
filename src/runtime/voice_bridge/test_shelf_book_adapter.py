import copy
import json
import tempfile
import unittest
from pathlib import Path
from .shelf_book_adapter import ShelfBookAdapter
from .pynq_service import compact_book_evidence, encode


class ShelfTests(unittest.TestCase):
    def test_transport_failure_is_distinct_from_ocr_miss(self):
        from ocr_link.client import NetworkError
        for failure,uploaded,expected in [(NetworkError('offline'),None,'ocr_service_unreachable'),
                                         (TimeoutError('deadline'),None,'ocr_service_unreachable'),
                                         (TimeoutError('deadline'),.2,'ocr_processing_timeout')]:
            with self.subTest(expected=expected),tempfile.TemporaryDirectory() as folder:
                adapter=self.setup_adapter(folder)
                def broken(payload,output,**kwargs):
                    (output/'transport.json').write_text(json.dumps(dict(upload_seconds=uploaded)))
                    raise failure
                adapter.client.run=broken
                with self.assertRaisesRegex(ValueError,expected):adapter.find('马克思主义基本原理')
                self.assertTrue(all(p==(0,0,0) for p in self.sent[-1]))

    def setup_adapter(self, folder, confidence=.99, missing=False, bad_hash=False):
        self.frames=0;self.sent=[]
        calibration=dict(camera='0',image_size=[1920,1080],
                         horizontal=[dict(index=i,xy=[100+(i-30)*100,1000]) for i in range(30,44)],
                         vertical=[dict(index=i,xy=[50,1000-(29-i)*100]) for i in range(29,20,-1)])
        class Lights:
            def show(_,channel,pixels,brightness):
                self.assertEqual(channel,0)  # All shelf and posture writes use LED1.
                self.sent.append(copy.deepcopy(pixels))
        class Client:
            def run(_,payload,output,**kwargs):
                return dict(status='succeeded',result=dict(request_id=payload['request_id'],
                    image_sha256='bad' if bad_hash else payload['image']['sha256'],source=copy.deepcopy(payload['source']),
                    matches=[] if missing else [dict(text='马克思主义基本原理',ocr_confidence=confidence,
                                                     book_box=[190,650,410,1005])]))
        def snapshot(after):
            self.frames+=1
            return b'\xff\xd8\xfftest',dict(sequence=self.frames,captured_monotonic=99+self.frames*.01,
                       captured_at='2026-10-28T00:00:00+00:00',device='0',actual_width=1920,actual_height=1080)
        return ShelfBookAdapter(Client(),Lights(),calibration,folder,snapshot,lambda c:None,clock=lambda:100)

    def test_confirmed_book_lights_only_measured_active_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder)
            result=adapter.find('马克思主义基本原理')
            self.assertTrue(result['indicator_lit']);self.assertEqual(self.frames,1)
            self.assertEqual(result['horizontal_physical'],[32,33,34])
            self.assertEqual(result['vertical_physical'],[27,28,29,30])
            self.assertTrue(all(pixel==(0,0,0) for i,pixel in enumerate(self.sent[-1]) if i<21 or i>43))
            self.assertLess(len(encode(dict(v=1,type='result',id='test',status='success',data=compact_book_evidence(result)))),2048)

    def test_single_frame_accepts_supported_lower_confidence(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder,confidence=.93)
            self.assertTrue(adapter.find('马克思主义基本原理')['found'])
            self.assertEqual(self.frames,1)

    def test_asr_prefix_rescue_uses_same_single_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder)
            result=adapter.find('马克马克思主义基本原理')
            self.assertTrue(result['found']);self.assertEqual(self.frames,1)
            self.assertEqual(result['title'],'马克思主义基本原理')
            self.assertEqual(result['requested_title'],'马克马克思主义基本原理')
            self.assertIn('单帧',compact_book_evidence(result)['message'])
            self.assertAlmostEqual(result['source']['age_at_result_seconds'],.99)

    def test_literal_repeated_title_has_priority_over_interpretation(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder);run=adapter.client.run
            def literal(payload,output,**kwargs):
                response=run(payload,output)
                response['result']['matches'][0]['text']='马克马克思主义基本原理'
                return response
            adapter.client.run=literal
            result=adapter.find('马克马克思主义基本原理')
            self.assertTrue(result['found']);self.assertEqual(self.frames,1)
            self.assertNotIn('query_normalization',result)

    def test_low_confidence_alias_cannot_find_a_book(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder,confidence=.89);run=adapter.client.run
            def once(payload,output,**kwargs):
                response=run(payload,output)
                if self.frames>1:response['result']['matches']=[]
                return response
            adapter.client.run=once
            self.assertFalse(adapter.find('马克马克思主义基本原理')['found'])

    def test_missing_first_frame_does_not_trigger_more_captures(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder,confidence=.93);run=adapter.client.run
            def late(payload,output,**kwargs):
                response=run(payload,output)
                if self.frames<3:response['result']['matches']=[]
                return response
            adapter.client.run=late
            self.assertFalse(adapter.find('马克思主义基本原理')['found'])
            self.assertEqual(self.frames,1)

    def test_nonrepeated_wrong_title_is_not_corrected(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder)
            self.assertFalse(adapter.find('马克斯主义基本原理')['found'])

    def test_recognized_book_with_failed_geometry_is_not_reported_missing(self):
        from unittest.mock import patch
        for reason in ('flat_spine_extent_unconfirmed','book_projection_outside_measured_leds'):
            with tempfile.TemporaryDirectory() as folder:
                adapter=self.setup_adapter(folder)
                with patch('voice_bridge.shelf_book_adapter.horizontal_mapping',side_effect=ValueError(reason)):
                    result=adapter.find('马克思主义基本原理')
                self.assertTrue(result['found'])
                self.assertFalse(result['indicator_lit'])
                self.assertEqual(result['geometry_status'],reason)
                self.assertTrue(all(p==(0,0,0) for p in self.sent[-1]))
                compact=compact_book_evidence(result)
                self.assertTrue(compact['found']);self.assertFalse(compact['indicator_lit'])
                self.assertIn('已识别到书名',compact['message'])

    def test_no_match_and_tampered_response_never_light(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder,missing=True)
            self.assertFalse(adapter.find('马克思主义基本原理')['indicator_lit'])
            self.assertEqual(self.frames,1)
            self.assertTrue(all(p==(0,0,0) for p in self.sent[-1]))
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder,bad_hash=True)
            with self.assertRaisesRegex(ValueError,'remote_book_result_invalid'):adapter.find('马克思主义基本原理')
            self.assertTrue(all(p==(0,0,0) for p in self.sent[-1]))

    def test_single_frame_conflicting_transcription_does_not_light(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder);run=adapter.client.run
            def conflicting(payload,output,**kwargs):
                response=run(payload,output)
                other=copy.deepcopy(response['result']['matches'][0]);other['text']='另一种同样长度的书名'
                response['result']['matches'].append(other)
                return response
            adapter.client.run=conflicting
            result=adapter.find('马克思主义基本原理')
            self.assertFalse(result['found']);self.assertEqual(self.frames,1)
            self.assertTrue(all(p==(0,0,0) for p in self.sent[-1]))

    def test_camera_move_rejects_before_ocr(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder)
            def moved(_):raise ValueError('camera_or_strip_moved_recalibrate')
            adapter.verify_anchors=moved
            with self.assertRaisesRegex(ValueError,'recalibrate'):adapter.find('马克思主义基本原理')
            self.assertEqual(self.frames,0)
            self.assertTrue(all(p==(0,0,0) for p in self.sent[-1]))

    def test_failed_calibration_preserves_old_file_and_blocks_find_until_recovered(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter=self.setup_adapter(folder)
            adapter.calibration_path=Path(folder)/'saved.json'
            original=json.dumps(adapter.calibration)
            adapter.calibration_path.write_text(original)
            def broken(output):raise ValueError('insufficient_calibration')
            adapter.calibrator=broken
            with self.assertRaisesRegex(ValueError,'insufficient_calibration'):adapter.calibrate()
            self.assertEqual(adapter.calibration_path.read_text(),original)
            self.assertTrue(adapter.calibration_path.with_suffix('.invalid').exists())
            with self.assertRaisesRegex(ValueError,'calibration_required'):adapter.find('马克思主义基本原理')
            adapter.calibrator=lambda output:adapter.calibration.copy()
            self.assertTrue(adapter.calibrate()['completed'])
            self.assertFalse(adapter.calibration_path.with_suffix('.invalid').exists())
            self.assertTrue(adapter.calibration_info()['calibrated'])


if __name__=='__main__':unittest.main()

