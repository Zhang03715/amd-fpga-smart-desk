"""Short LCD labels; stale or malformed posture output must never look normal."""
import json
import math
from pathlib import Path


def posture_label(path, now):
    try:
        record = json.loads(Path(path).read_text())
        age = now-record['captured_monotonic']
        if not math.isfinite(age) or age < 0:
            return 'Pose: waiting / stale'
        result = record['assessment']
        # Diagnostic history has explicit age; it never makes an old frame a
        # fresh detection or changes the reminder gate. Require recent producer
        # completion as well, so a dead worker cannot leave a normal label.
        if 'state' in result and 'age_seconds' in record:
            processing_age = record['age_seconds']
            completed_age = age-processing_age
            if (not math.isfinite(processing_age) or processing_age < 0
                    or not 0 <= completed_age <= 2.5 or age > 5):
                return 'Pose: waiting / stale'
            reasons = result.get('reasons',[])
            if 'stale_frame' in reasons:
                return 'Pose: inference too slow'
            label = {'within_reference':'upright','head_lowered':'reading/head down',
                     'normal':'normal','head_down':'head down','shoulder_tilt':'shoulder tilt',
                     'head_down_and_shoulder_tilt':'head down + tilt',
                     'deep_head_lowered':'head too low','lateral_deviation':'side lean',
                     'calibration_needed':'calibrate first'}.get(result['state'],'cannot judge')
            if 'insufficient_landmark_evidence' in reasons:label='need face/shoulders'
            if 'camera_or_seating_changed_recalibrate' in reasons:label='move back/recalib'
            return '%s: %s %.1fs' % ('Pose' if age <= 2 else 'Last',label,age)
        if age > 2:
            return 'Pose: waiting / stale'
        if 'state' in result:
            return {'within_reference':'Pose: upright',
                    'head_lowered':'Pose: reading / head down',
                    'deep_head_lowered':'Pose: head too low',
                    'lateral_deviation':'Pose: leaning sideways',
                    'calibration_needed':'Pose: calibrate first',
                    'unknown':'Pose: cannot judge'}.get(result['state'],'Pose: cannot judge')
        if result['status'] == 'within_reference':
            return 'Pose: within reference'
        if result['status'] == 'deviation':
            return 'Pose: tilt / head offset'
        if result['status'] == 'calibration_needed':
            return 'Pose: calibrate first'
        return 'Pose: cannot judge'
    except (OSError, ValueError, TypeError, KeyError):
        return 'Pose: waiting'
