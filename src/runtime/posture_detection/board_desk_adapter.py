"""COCO-17 NCNN adapter for the independent front-view desk candidate.

Packaged as upper_body.py beside board_upper_probe.py in an isolated deployment.
Old status strings support the existing LCD protocol; detailed state is retained.
"""
from posture_detection.desk_rules import assess as desk_assess, calibrate as desk_calibrate


def _landmarks(points,size):
    landmarks=[]
    if len(points)==17:
        width,height=size
        landmarks=[dict(x=0.,y=0.,visibility=0.,presence=1.,z=0.) for _ in range(33)]
        for target,source in [(0,0),(11,5),(12,6)]:
            x,y,confidence=points[source]
            landmarks[target].update(x=x/width,y=y/height,visibility=confidence)
    return landmarks


def assess(points,size,baseline=None,camera_id='camera0',age_seconds=0):
    result=desk_assess(_landmarks(points,size),size,baseline,'front',camera_id,age_seconds)
    result['status']={'within_reference':'within_reference','calibration_needed':'calibration_needed',
                      'unknown':'unknown','head_lowered':'within_reference',
                      'deep_head_lowered':'deviation','lateral_deviation':'deviation'}[result['state']]
    result['alert']=False
    return result


def assess_simple(points,size,baseline=None,camera_id='camera0',age_seconds=0):
    from posture_detection.simple_front import assess as simple_assess
    result=simple_assess(_landmarks(points,size),size,baseline,camera_id,age_seconds)
    result['status']=('unknown' if result['state']=='unknown' else
                      'calibration_needed' if result['state']=='calibration_needed' else
                      'within_reference' if result['state']=='normal' else 'deviation')
    result['alert']=False
    return result


def calibrate(samples,camera_id):
    result=desk_calibrate(samples,'front',camera_id)
    result['keypoint_backend']='board_ncnn_int8_coco17'
    return result


def eligible_front_candidates(candidates,size):
    """Return all evidence-valid indices. Caller must require exactly one."""
    return [i for i,points in enumerate(candidates)
            if assess(points,size)['state']=='calibration_needed']
