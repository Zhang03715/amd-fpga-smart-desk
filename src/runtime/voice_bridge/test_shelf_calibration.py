import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from .pynq_service import DeskService,encode
from .shelf_calibration import verify_anchors,AnchorError


class CalibrationTests(unittest.TestCase):
    def test_missing_pixel_prior_is_bounded_and_not_a_measurement(self):
        from .shelf_calibration import expected_point
        reference={'horizontal':[dict(index=39,xy=[1177,953]),dict(index=42,xy=[1486,957])]}
        self.assertAlmostEqual(expected_point(reference,'horizontal',40)[0],1280)
        self.assertAlmostEqual(expected_point(reference,'horizontal',41)[0],1383)
        self.assertAlmostEqual(expected_point(reference,'horizontal',43)[0],1589)
        self.assertIsNone(expected_point(reference,'horizontal',44))
        self.assertIsNone(expected_point(None,'horizontal',40))

    def test_white_led_core_wins_over_nearby_red_reflection(self):
        import cv2
        import numpy as np
        from .shelf_calibration import marker
        off=np.zeros((1080,1920,3),dtype=np.uint8);on=off.copy()
        cv2.circle(on,(500,500),20,(0,0,240),-1)
        cv2.circle(on,(460,500),16,(0,0,170),-1)
        cv2.circle(on,(460,500),7,(240,240,255),-1)
        r=marker(cv2.imencode('.png',off)[1].tobytes(),cv2.imencode('.png',on)[1].tobytes())
        self.assertEqual(r['method'],'illumination_core')
        self.assertLess(np.linalg.norm(np.array(r['xy'])-[460,500]),5)

    def test_native_refinement_does_not_hide_a_real_shift(self):
        import cv2
        import numpy as np
        from .shelf_calibration import marker
        off=np.zeros((1080,1920,3),dtype=np.uint8);on=off.copy()
        cv2.circle(on,(180,100),18,(0,0,240),-1)
        r=marker(cv2.imencode('.png',off)[1].tobytes(),cv2.imencode('.png',on)[1].tobytes(),[100,100])
        self.assertFalse(r['matched'])
        self.assertGreater(np.linalg.norm(np.array(r['xy'])-[100,100]),60)

    def test_bright_reflection_does_not_replace_a_valid_expected_light(self):
        import cv2
        import numpy as np
        from .shelf_calibration import marker
        off=np.zeros((1080,1920,3),dtype=np.uint8);on=off.copy()
        cv2.circle(on,(200,200),18,(0,0,200),-1)
        cv2.circle(on,(1000,500),18,(0,0,250),-1)
        result=marker(cv2.imencode('.png',off)[1].tobytes(),cv2.imencode('.png',on)[1].tobytes(),[200,200])
        self.assertTrue(result['matched']);self.assertLess(result['distance'],20)

    def test_async_voice_job_retries_do_not_rescan_and_query_returns_completion(self):
        gate=threading.Event();calls=[]
        class Adapter:
            max_pending_jobs=1
            def calibrate(self):
                calls.append(1);gate.wait(2)
                return dict(completed=True,state='calibrated',horizontal_count=12,vertical_count=8)
            def calibration_info(self):return dict(calibrated=True)
            def find(self,*args):raise AssertionError('calibration owns the worker')
        service=DeskService(book_adapter=Adapter())
        request=dict(v=1,type='request',id='cal-1',action='light.calibration',params={'mode':'start'})
        try:
            self.assertEqual(service.handle(request)['status'],'pending')
            self.assertEqual(service.handle(request)['status'],'pending')
            busy=service.handle(dict(v=1,type='request',id='find-1',action='book.find',params={'title':'书'}))
            self.assertEqual(busy['error'],'book_scan_busy')
            gate.set();service.jobs['cal-1']['future'].result(timeout=2)
            event=service.poll_events()[0]
            self.assertTrue(event['data']['completed']);self.assertLess(len(encode(event)),2048)
            self.assertEqual(calls,[1])
            status=service.handle(dict(v=1,type='request',id='status-1',action='light.calibration',params={'mode':'status'}))
            self.assertTrue(status['data']['calibrated']);self.assertEqual(calls,[1])
        finally:gate.set();service.close()

    def test_retry_recovers_a_transient_and_always_clears(self):
        frames=[]
        class Lights:
            def show(self,channel,pixels,brightness):frames.append(pixels)
        def snapshot(after):return b'jpeg',dict(device='0')
        calibration=dict(camera='0',horizontal=[dict(index=30,xy=[100,100])],vertical=[dict(index=29,xy=[100,200])])
        records=[dict(peak=20,xy=[800,400],matched=False),dict(peak=200,xy=[100,100],matched=True),dict(peak=200,xy=[100,200],matched=True)]
        with patch('voice_bridge.shelf_calibration.marker',side_effect=records):
            audit=verify_anchors(Lights(),snapshot,calibration)
        self.assertEqual(len(audit),3)
        self.assertTrue(all(p==(0,0,0) for p in frames[-1]))

    def test_missing_light_is_not_reported_as_camera_movement(self):
        class Lights:
            def show(self,*args,**kwargs):pass
        calibration=dict(camera='0',horizontal=[dict(index=30,xy=[100,100])],vertical=[])
        with patch('voice_bridge.shelf_calibration.marker',return_value=dict(peak=3,xy=[800,400],matched=False)):
            with self.assertRaisesRegex(AnchorError,'check_power_or_occlusion') as caught:
                verify_anchors(Lights(),lambda after:(b'jpeg',dict(device='0')),calibration)
            self.assertEqual(len(caught.exception.audit),2)

    def test_consistent_shift_requires_recalibration(self):
        class Lights:
            def show(self,*args,**kwargs):pass
        calibration=dict(camera='0',horizontal=[dict(index=30,xy=[100,100])],vertical=[])
        with patch('voice_bridge.shelf_calibration.marker',return_value=dict(peak=200,xy=[180,100],matched=False)):
            with self.assertRaisesRegex(AnchorError,'moved_recalibrate'):
                verify_anchors(Lights(),lambda after:(b'jpeg',dict(device='0')),calibration)


if __name__=='__main__':unittest.main()
