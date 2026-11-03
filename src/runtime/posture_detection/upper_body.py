"""Front-view COCO-17 cues for desks where hips are hidden.

These relative 2D cues cannot assess trunk lean or forward head posture.
"""
import math
import statistics


LIMITS = {'shoulder_angle': 10.0, 'head_offset': 0.18}


def features(points, size, confidence=0.65):
    try:
        width, height = size
        if width <= 0 or height <= 0 or len(points) != 17:
            return None
        for index in (0, 5, 6):
            x, y, score = points[index]
            if not all(math.isfinite(v) for v in (x, y, score)):
                return None
            if not (0 <= x < width and 0 <= y < height and confidence <= score <= 1):
                return None
        nose, a, b = (points[i] for i in (0, 5, 6))
        left, right = sorted((a, b), key=lambda p: p[0])
        span = math.hypot(right[0]-left[0], right[1]-left[1])
        cx, cy = (a[0]+b[0])/2, (a[1]+b[1])/2
        if span < width*0.1 or nose[1] >= cy:
            return None
        return {
            'shoulder_angle': math.degrees(math.atan2(right[1]-left[1], right[0]-left[0])),
            'head_offset': (nose[0]-cx)/span,
            'scale': span/width, 'center_x': cx/width, 'center_y': cy/height,
            'aspect': width/height,
        }
    except (TypeError, ValueError, IndexError):
        return None


def calibrate(samples, camera_id, min_samples=15):
    """Caller must supply distinct fresh frames of a stated reference posture."""
    if len(samples) < min_samples or any(s is None for s in samples):
        raise ValueError('not_enough_valid_samples')
    median = {k: statistics.median(s[k] for s in samples) for k in samples[0]}
    for key, limit in {**{k: v/2 for k, v in LIMITS.items()},
                       'scale': median['scale']*.10, 'center_x': .05, 'center_y': .05}.items():
        if max(abs(s[key]-median[key]) for s in samples) > limit:
            raise ValueError('unstable_calibration')
    return {'schema': 1, 'mode': 'front_upper_body', 'camera_id': camera_id,
            'metrics': median, 'samples': len(samples)}


def assess(points, size, baseline=None, camera_id='camera0', age_seconds=0):
    out = {'mode': 'front_upper_body', 'status': 'unknown', 'alert': False,
           'unsupported': ['trunk_lean', 'forward_head'], 'metrics': None}
    if not math.isfinite(age_seconds) or not 0 <= age_seconds <= 2:
        return dict(out, reason='stale_frame')
    metrics = features(points, size)
    if metrics is None:
        return dict(out, reason='insufficient_face_or_shoulders')
    out['metrics'] = metrics
    if baseline is None:
        return dict(out, status='calibration_needed', reason='personal_reference_required')
    try:
        if baseline['schema'] != 1 or baseline['mode'] != out['mode'] or baseline['camera_id'] != camera_id:
            raise ValueError()
        b = baseline['metrics']
        if any(not math.isfinite(b[k]) for k in metrics) or b['scale'] <= 0:
            raise ValueError()
        if (abs(metrics['scale']/b['scale']-1) > .3
                or abs(metrics['aspect']/b['aspect']-1) > .05
                or math.hypot(metrics['center_x']-b['center_x'], metrics['center_y']-b['center_y']) > .22):
            return dict(out, reason='camera_or_seating_changed_recalibrate')
        reasons = [k for k, limit in LIMITS.items() if abs(metrics[k]-b[k]) > limit]
        return dict(out, status='deviation' if reasons else 'within_reference', reasons=reasons)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return dict(out, reason='invalid_calibration')
