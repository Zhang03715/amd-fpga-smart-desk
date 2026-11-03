"""Calibrated 2D posture cues, not medical/spinal angle measurements.

Coordinates use MediaPipe's unmirrored 33-landmark convention. Confidence is
minimum required landmark visibility/presence, not probability of bad posture.
"""
import math
import statistics

DEFAULT_CONFIG = {
    'min_confidence': 0.65, 'max_age': 2.0, 'min_samples': 15,
    'min_scale': 0.06, 'max_scale_change': 0.30,
    'max_center_shift': 0.22, 'max_aspect_change': 0.05,
    'front_lean_delta_degrees': 10.0, 'front_head_drop_delta': 0.20,
    'side_head_offset_delta': 0.18, 'side_trunk_delta_degrees': 12.0,
    'max_calibration_spread': 0.10,
}


def _config(config):
    out = dict(DEFAULT_CONFIG)
    if config:
        unknown = set(config) - set(out)
        if unknown:
            raise ValueError('unknown thresholds: ' + ','.join(sorted(unknown)))
        out.update(config)
    for key, value in out.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('invalid threshold: ' + key)
    if out['min_confidence'] > 1 or int(out['min_samples']) != out['min_samples']:
        raise ValueError('invalid confidence/sample threshold')
    return out


def _unknown(reason, confidence=0.0, metrics=None):
    return {'valid': False, 'classification': 'unknown', 'reasons': [reason],
            'confidence': confidence, 'metrics': metrics or {}}


def extract_features(landmarks, image_size, view='front', config=None):
    """Extract upper-body cues; all required points must be in frame.

    Side view chooses the more confidently visible body side and records it.
    Front view needs nose/both shoulders/both hips. Side needs ear/shoulder/hip.
    """
    cfg = _config(config)
    if view not in ('front', 'side'):
        raise ValueError('view must be front or side')
    if not landmarks or len(landmarks) != 33:
        return _unknown('no_person_or_invalid_landmarks')
    try:
        width, height = image_size
        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
            return _unknown('invalid_image_size')
        def confidence(index):
            point = landmarks[index]
            return min(float(point.get('visibility', 0)), float(point.get('presence', 0)))
        side = 'front'
        indices = [0, 11, 12, 23, 24]
        if view == 'side':
            left, right = [7, 11, 23], [8, 12, 24]
            side = 'left' if min(map(confidence, left)) >= min(map(confidence, right)) else 'right'
            indices = left if side == 'left' else right
        minimum = min(map(confidence, indices))
        for index in indices:
            p = landmarks[index]
            values = [float(p[key]) for key in ('x', 'y', 'z')]
            values += [float(p.get(key, 0)) for key in ('visibility', 'presence')]
            if not all(math.isfinite(v) for v in values):
                return _unknown('nonfinite_landmark')
            if not 0 <= values[0] <= 1 or not 0 <= values[1] <= 1:
                return _unknown('required_point_out_of_frame')
            if not all(0 <= v <= 1 for v in values[3:]):
                return _unknown('invalid_landmark_confidence')
        if minimum < cfg['min_confidence']:
            return _unknown('occluded_or_low_confidence', minimum)
        def xy(index):
            p = landmarks[index]
            return (p['x'] * width / height, p['y'])
        if view == 'front':
            a, b = xy(11), xy(12)
            shoulder = ((a[0]+b[0])/2, (a[1]+b[1])/2)
            hip_a, hip_b = xy(23), xy(24)
            hip = ((hip_a[0]+hip_b[0])/2, (hip_a[1]+hip_b[1])/2)
            head = xy(0)
            scale = math.dist(a, b)
            lean = math.degrees(math.atan2(b[1]-a[1], abs(b[0]-a[0])))
            metrics = {'lean_degrees': lean, 'head_height': (shoulder[1]-head[1])/max(scale, 1e-9)}
        else:
            head, shoulder, hip = map(xy, indices)
            scale = math.dist(shoulder, hip)
            metrics = {'head_offset': (head[0]-shoulder[0])/max(scale, 1e-9),
                       'trunk_degrees': math.degrees(math.atan2(shoulder[0]-hip[0], hip[1]-shoulder[1]))}
        if scale < cfg['min_scale'] or hip[1] <= shoulder[1]:
            return _unknown('unusable_body_geometry', minimum)
        metrics.update(scale=scale, center_x=shoulder[0], center_y=shoulder[1],
                       aspect=width/height, side=side)
        return {'valid': True, 'reasons': [], 'confidence': minimum, 'metrics': metrics}
    except (TypeError, ValueError, KeyError, IndexError, OverflowError):
        return _unknown('invalid_landmarks')


def calibrate(samples, view='front', config=None, camera_id='default'):
    """Median personal baseline from distinct valid samples supplied by caller.

    Caller must collect separate live/video frames while user sits comfortably
    upright; repeated still images must not be accepted as multiple samples.
    """
    cfg = _config(config)
    if view not in ('front', 'side'):
        raise ValueError('invalid view')
    valid = [sample for sample in samples if sample.get('valid')]
    if len(valid) < cfg['min_samples']:
        raise ValueError('not_enough_valid_calibration_samples')
    sides = {sample['metrics']['side'] for sample in valid}
    if len(sides) != 1:
        raise ValueError('body_side_changed_during_calibration')
    keys = list(valid[0]['metrics'])
    metrics = {key: statistics.median(sample['metrics'][key] for sample in valid)
               for key in keys if key != 'side'}
    metrics['side'] = next(iter(sides))
    for key in ('scale', 'center_x', 'center_y'):
        spread = max(abs(sample['metrics'][key]-metrics[key]) for sample in valid)
        if spread > cfg['max_calibration_spread'] * (metrics['scale'] if key == 'scale' else 1):
            raise ValueError('unstable_calibration')
    limits = ({'lean_degrees': cfg['front_lean_delta_degrees']/2,
               'head_height': cfg['front_head_drop_delta']/2} if view == 'front' else
              {'head_offset': cfg['side_head_offset_delta']/2,
               'trunk_degrees': cfg['side_trunk_delta_degrees']/2})
    for key, limit in limits.items():
        if max(abs(sample['metrics'][key]-metrics[key]) for sample in valid) > limit:
            raise ValueError('posture_changed_during_calibration')
    return {'schema_version': 1, 'view': view, 'camera_id': camera_id,
            'metrics': metrics, 'sample_count': len(valid)}


def classify(landmarks, image_size, baseline=None, view='front', age_seconds=0,
             config=None, camera_id='default'):
    cfg = _config(config)
    if not isinstance(age_seconds, (int, float)) or not math.isfinite(age_seconds) or age_seconds < 0 or age_seconds > cfg['max_age']:
        return _unknown('stale_or_invalid_frame_time')
    result = extract_features(landmarks, image_size, view, cfg)
    if not result['valid']:
        return result
    if not baseline:
        return _unknown('personal_calibration_required', result['confidence'], result['metrics'])
    if not isinstance(baseline, dict):
        return _unknown('invalid_calibration', result['confidence'], result['metrics'])
    if baseline.get('schema_version') != 1 or baseline.get('view') != view or baseline.get('camera_id') != camera_id:
        return _unknown('calibration_camera_or_view_mismatch', result['confidence'], result['metrics'])
    m, b = result['metrics'], baseline.get('metrics', {})
    try:
        if any(not math.isfinite(b[k]) for k in m if k != 'side') or b['scale'] <= 0:
            raise ValueError()
        changed = (m['side'] != b['side'] or abs(m['scale']/b['scale']-1) > cfg['max_scale_change']
                   or abs(m['aspect']/b['aspect']-1) > cfg['max_aspect_change']
                   or math.hypot(m['center_x']-b['center_x'], m['center_y']-b['center_y']) > cfg['max_center_shift'])
        if changed:
            return _unknown('camera_or_seating_geometry_changed_recalibrate', result['confidence'], m)
        reasons = []
        if view == 'front':
            if abs(m['lean_degrees']-b['lean_degrees']) > cfg['front_lean_delta_degrees']:
                reasons.append('lateral_shoulder_tilt')
            if b['head_height']-m['head_height'] > cfg['front_head_drop_delta']:
                reasons.append('head_lower_than_personal_baseline')
        else:
            if abs(m['head_offset']-b['head_offset']) > cfg['side_head_offset_delta']:
                reasons.append('ear_shoulder_offset_changed_2d')
            if abs(m['trunk_degrees']-b['trunk_degrees']) > cfg['side_trunk_delta_degrees']:
                reasons.append('trunk_projection_tilt_changed_2d')
        result.update(classification='bad' if reasons else 'good', reasons=reasons or ['within_personal_baseline_thresholds'])
        return result
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return _unknown('invalid_calibration', result['confidence'], m)
