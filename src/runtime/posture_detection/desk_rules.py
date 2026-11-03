"""Experimental desk-view cues, separate from the deployed rule set.

Outputs describe 2D changes; reading/head translation alone is not a reminder
candidate. No medical classification or live alert delivery is performed.
"""
import math
import statistics
from .rules import extract_features

LIMITS = dict(shoulder_angle=10., head_offset=.18, head_drop=.20,
              trunk_degrees=12., max_scale_change=.30, max_center_shift=.22)


def features(landmarks, size, view):
    if view == 'side':
        result=extract_features(landmarks,size,'side')
        return result['metrics'] if result['valid'] else None
    if view != 'front':raise ValueError('Unsupported view')
    try:
        width,height=size
        if len(landmarks)!=33 or not all(math.isfinite(v) and v>0 for v in (width,height)):return None
        points=[]
        for i in (0,11,12):
            p=landmarks[i];x,y,c=float(p['x']),float(p['y']),float(p['visibility'])
            if not all(math.isfinite(v) for v in (x,y,c)) or not (0<=x<=1 and 0<=y<=1 and .65<=c<=1):return None
            points.append((x*width,y*height))
        nose,a,b=points;left,right=sorted((a,b));span=math.dist(a,b)
        if span<width*.1:return None
        cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
        dx,dy=right[0]-left[0],right[1]-left[1]
        # Project onto the shoulder frame so camera/body roll alone does not
        # turn horizontal displacement into a spurious vertical head drop.
        return dict(shoulder_angle=math.degrees(math.atan2(right[1]-left[1],right[0]-left[0])),
                    head_offset=(dx*(nose[0]-cx)+dy*(nose[1]-cy))/(span*span),
                    head_height=(dy*(nose[0]-cx)+dx*(cy-nose[1]))/(span*span),
                    scale=span/width,center_x=cx/width,center_y=cy/height,
                    aspect=width/height,side='front')
    except (ValueError,TypeError,KeyError,IndexError):return None


def calibrate(samples,view,camera_id):
    """Caller supplies >=15 distinct valid reference frames, never repeated stills."""
    if view not in ('front','side'):raise ValueError('Unsupported view')
    if len(samples)<15 or any(s is None for s in samples):raise ValueError('insufficient_samples')
    if len({s['side'] for s in samples})!=1:raise ValueError('unstable_body_side')
    median={k:statistics.median(s[k] for s in samples) for k in samples[0] if k!='side'}
    median['side']=samples[0]['side']
    limits=dict(scale=median['scale']*.1,center_x=.05,center_y=.05)
    if view=='front':limits.update(shoulder_angle=5,head_offset=.09,head_height=.10)
    else:limits.update(trunk_degrees=6,head_offset=.09)
    for k,limit in limits.items():
        if max(abs(s[k]-median[k]) for s in samples)>limit:raise ValueError('unstable_reference_'+k)
    return dict(schema=2,view=view,camera_id=camera_id,metrics=median,samples=len(samples))


def assess(landmarks,size,baseline,view,camera_id,age_seconds=0):
    out=dict(state='unknown',reminder_candidate=False,metrics=None,reasons=[])
    if not math.isfinite(age_seconds) or not 0<=age_seconds<=2:
        return dict(out,reasons=['stale_frame'])
    m=features(landmarks,size,view)
    if m is None:return dict(out,reasons=['insufficient_landmark_evidence'])
    out['metrics']=m
    if baseline is None:return dict(out,state='calibration_needed')
    try:
        if baseline['schema']!=2 or baseline['view']!=view or baseline['camera_id']!=camera_id:raise ValueError()
        b=baseline['metrics']
        if any(not math.isfinite(b[k]) for k in m if k!='side') or b['scale']<=0:raise ValueError()
        if (m['side']!=b['side'] or abs(m['scale']/b['scale']-1)>LIMITS['max_scale_change']
                or abs(m['aspect']/b['aspect']-1)>.05
                or math.hypot(m['center_x']-b['center_x'],m['center_y']-b['center_y'])>LIMITS['max_center_shift']):
            return dict(out,reasons=['camera_or_seating_changed_recalibrate'])
        if view=='front':
            lateral=(abs(m['head_offset']-b['head_offset'])>LIMITS['head_offset']
                     or abs(m['shoulder_angle']-b['shoulder_angle'])>LIMITS['shoulder_angle'])
            drop=b['head_height']-m['head_height']
            # A nose below the shoulder midpoint can occur in a strongly lowered
            # head projection. It is not rejected as invalid body geometry.
            deep=drop>LIMITS['head_drop'] and m['head_height']<=0
            reasons=(['lateral_change'] if lateral else [])+(['deep_head_projection'] if deep else [])
            if reasons:return dict(out,state='lateral_deviation' if lateral else 'deep_head_lowered',
                                   reminder_candidate=True,reasons=reasons)
            if drop>LIMITS['head_drop']:return dict(out,state='head_lowered',reasons=['reading_or_head_change'])
        else:
            if abs(m['trunk_degrees']-b['trunk_degrees'])>LIMITS['trunk_degrees']:
                return dict(out,state='trunk_lean',reminder_candidate=True,reasons=['trunk_projection_changed'])
            if abs(m['head_offset']-b['head_offset'])>LIMITS['head_offset']:
                return dict(out,state='reading_or_head_shift',reasons=['ambiguous_without_trunk_change'])
        return dict(out,state='within_reference')
    except (KeyError,ValueError,TypeError,ZeroDivisionError):return dict(out,reasons=['invalid_calibration'])


class SustainedCue:
    """Offline persistence diagnostic. Never generates a live reminder event."""
    def __init__(self,duration=3.,max_gap=.6):
        if not (math.isfinite(duration) and math.isfinite(max_gap) and duration>0 and max_gap>0):raise ValueError('Invalid timing')
        self.duration,self.max_gap=duration,max_gap
        self.last=None;self.frame=None;self.session=None;self.since=None;self.state=None

    def update(self,now,frame,session,result):
        if not math.isfinite(now):self.since=None;return False
        invalid=(self.last is not None and (now<=self.last or frame==self.frame))
        gap=(self.last is None or now-self.last>self.max_gap or session!=self.session)
        self.last,self.frame,self.session=now,frame,session
        if invalid or not result['reminder_candidate']:
            self.since=None;self.state=None;return False
        if gap or self.since is None or result['state']!=self.state:self.since=now
        self.state=result['state']
        return now-self.since>=self.duration
