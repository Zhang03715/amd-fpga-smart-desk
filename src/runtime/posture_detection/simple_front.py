"""Front-only display cues: head down, shoulder tilt, or reference-normal.

Low head projection describes an action, not a judgment that reading is bad.
Reuses v2 landmark/calibration/geometry guards and its personal baseline.
"""
from .desk_rules import assess as guarded_assess, LIMITS


def assess(landmarks,size,baseline,camera_id,age_seconds=0):
    result=guarded_assess(landmarks,size,baseline,'front',camera_id,age_seconds)
    result.update(mode='simple_front',reminder_candidate=False)
    if result['state'] in ('unknown','calibration_needed'):
        result['head_down']=None;result['shoulder_tilt']=None
        return result
    m,b=result['metrics'],baseline['metrics']
    head_down=b['head_height']-m['head_height']>LIMITS['head_drop']
    tilted=abs(m['shoulder_angle']-b['shoulder_angle'])>LIMITS['shoulder_angle']
    state=('head_down_and_shoulder_tilt' if head_down and tilted else
           'head_down' if head_down else 'shoulder_tilt' if tilted else 'normal')
    result.update(state=state,head_down=head_down,shoulder_tilt=tilted,
                  reasons=(['head_lower_than_reference'] if head_down else [])+
                          (['shoulder_line_tilt'] if tilted else []))
    return result
