"""Short reference capture using distinct inferred frames, with stability checks."""
import statistics

def calibrate_reference(samples,camera_id):
    if len(samples)<3 or any(s is None for s in samples):raise ValueError('insufficient_samples')
    if len({s['side'] for s in samples})!=1:raise ValueError('unstable_body_side')
    median={k:statistics.median(s[k] for s in samples) for k in samples[0] if k!='side'}
    median['side']=samples[0]['side']
    limits=dict(scale=median['scale']*.1,center_x=.05,center_y=.05,
                shoulder_angle=5,head_offset=.09,head_height=.10)
    for key,limit in limits.items():
        if max(abs(s[key]-median[key]) for s in samples)>limit:raise ValueError('unstable_reference_'+key)
    return dict(schema=2,view='front',camera_id=camera_id,metrics=median,samples=len(samples),
                keypoint_backend='board_ncnn_int8_coco17')
