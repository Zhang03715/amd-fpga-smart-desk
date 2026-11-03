"""Measured shelf calibration and auditable optical anchor checks."""
# FPGA channel 0 = connector LED1; pixel order and optical coordinates stay unchanged.
SHELF_LED_CHANNEL = 0
import json
import time
from pathlib import Path


def marker(off, on, expected=None):
    import cv2
    import numpy as np
    images=[cv2.imdecode(np.frombuffer(d,np.uint8),cv2.IMREAD_COLOR) for d in (off,on)]
    if any(im is None or list(im.shape[1::-1])!=[1920,1080] for im in images):
        raise ValueError('calibration_source_mismatch')
    # Locate the halo at half resolution, then measure its native-pixel ROI.
    # Avoid full-HD float arrays and convolutions on the Z2 ARM processor.
    small=[cv2.resize(im,(960,540),interpolation=cv2.INTER_AREA).astype(np.float32) for im in images]
    delta=small[1]-small[0]
    score=cv2.GaussianBlur(np.maximum(0,delta[:,:,2]-.5*(delta[:,:,0]+delta[:,:,1])),(11,11),0)
    _,_,_,seed=cv2.minMaxLoc(score)
    def field(seed,radius):
        x,y=seed;left,right=max(0,x-radius),min(1920,x+radius+1);top,bottom=max(0,y-radius),min(1080,y+radius+1)
        d=images[1][top:bottom,left:right].astype(np.float32)-images[0][top:bottom,left:right].astype(np.float32)
        s=cv2.GaussianBlur(np.maximum(0,d[:,:,2]-.5*(d[:,:,0]+d[:,:,1])),(21,21),0)
        return d,s,left,top
    native_delta,native_score,left,top=field((seed[0]*2,seed[1]*2),110)
    _,peak,_,local_seed=cv2.minMaxLoc(native_score)
    xy=(local_seed[0]+left,local_seed[1]+top)
    # The LED's saturated core can look white while a red reflection on a book
    # has stronger chroma. Find the compact illumination core near that halo;
    # retain pure-red detection when no white/high-energy core is observed.
    def core(seed,red_peak,d,s,origin,bounds=None):
        ox,oy=origin;x,y=seed[0]-ox,seed[1]-oy
        left,right=max(0,x-75),min(d.shape[1],x+76);top,bottom=max(0,y-75),min(d.shape[0],y+76)
        if bounds is not None:
            left=max(left,bounds[0]);top=max(top,bounds[1]);right=min(right,bounds[2]);bottom=min(bottom,bounds[3])
        energy=cv2.GaussianBlur(np.maximum(d[top:bottom,left:right],0).sum(axis=2),(5,5),0)
        _,value,_,point=cv2.minMaxLoc(energy)
        point=(point[0]+left,point[1]+top)
        use=value>=red_peak*1.35 and s[point[1],point[0]]>=red_peak*.15 and red_peak>=15
        return ((point[0]+ox,point[1]+oy) if use else seed),dict(method='illumination_core' if use else 'red_chroma',core_peak=float(value))
    centre,details=core(xy,peak,native_delta,native_score,(left,top))
    result=dict(peak=float(peak),xy=list(centre),red_halo_xy=list(xy),**details)
    if expected is not None:
        x,y=map(int,expected);d,s,left,top=field((x,y),55)
        bounds=(max(0,x-35-left),max(0,y-35-top),min(s.shape[1],x+36-left),min(s.shape[0],y+36-top))
        a,b,c,e=bounds
        _,local,_,point=cv2.minMaxLoc(s[b:e,a:c])
        point=[point[0]+a+left,point[1]+b+top]
        point,local_details=core(point,local,d,s,(left,top),bounds)
        distance=float(np.linalg.norm(np.array(point)-expected))
        result.update(local_peak=float(local),local_xy=list(point),local_method=local_details['method'],distance=distance,
                      matched=local>=15 and local>=peak*.6 and distance<=35)
    return result


class AnchorError(ValueError):
    def __init__(self, reason, audit):
        super().__init__(reason);self.audit=audit


def verify_anchors(lights,snapshot,calibration):
    import math
    audit=[];black=[(0,0,0)]*60
    try:
        for axis in ('horizontal','vertical'):
            point=calibration[axis][0];attempts=[]
            for attempt in range(2):
                lights.show(SHELF_LED_CHANNEL,black,brightness=.10);off,oi=snapshot(time.monotonic()+.05)
                pixels=black.copy();pixels[point['index']]=(255,0,0)
                lights.show(SHELF_LED_CHANNEL,pixels,brightness=.10);on,ni=snapshot(time.monotonic()+.05)
                if oi['device']!=calibration['camera'] or ni['device']!=calibration['camera']:
                    raise AnchorError('calibration_source_mismatch',audit)
                record=dict(axis=axis,physical=point['index']+1,attempt=attempt+1,
                            expected=point['xy'],**marker(off,on,point['xy']))
                audit.append(record);attempts.append(record)
                if record['matched']:break
            else:
                a,b=attempts
                stable=math.dist(a['xy'],b['xy'])<=20
                shifted=all(r['peak']>=15 and math.dist(r['xy'],point['xy'])>35 for r in attempts)
                reason='camera_or_strip_moved_recalibrate' if stable and shifted else 'led_anchor_unstable_check_power_or_occlusion'
                raise AnchorError(reason,audit)
        return audit
    finally:
        lights.show(SHELF_LED_CHANNEL,black,brightness=.10)


def grouped_markers(off,on,axis,indices,reference):
    """Use existing coordinates to disambiguate simultaneous LEDs; reject ambiguity."""
    import cv2,numpy as np,math
    images=[cv2.imdecode(np.frombuffer(d,np.uint8),cv2.IMREAD_COLOR) for d in (off,on)]
    if any(im is None or list(im.shape[1::-1])!=[1920,1080] for im in images):raise ValueError('calibration_source_mismatch')
    small=[cv2.resize(im,(960,540),interpolation=cv2.INTER_AREA).astype(np.float32) for im in images]
    d=small[1]-small[0];score=cv2.GaussianBlur(np.maximum(0,d[:,:,2]-.5*(d[:,:,0]+d[:,:,1])),(7,7),0)
    mask=(score>=max(15,float(score.max())*.30)).astype(np.uint8)
    n,labels,stats,centres=cv2.connectedComponentsWithStats(mask)
    candidates=[]
    for i in range(1,n):
        if stats[i,cv2.CC_STAT_AREA]<3:continue
        _,peak,_,xy=cv2.minMaxLoc(score,mask=(labels==i).astype(np.uint8))
        candidates.append(dict(xy=[xy[0]*2,xy[1]*2],peak=float(peak),method='group_red_chroma',red_halo_xy=[xy[0]*2,xy[1]*2]))
    if len(candidates)!=len(indices):raise ValueError('ambiguous_group_count')
    candidates.sort(key=lambda p:p['xy'][0] if axis=='horizontal' else -p['xy'][1])
    expected={p['index']:p['xy'] for p in reference[axis]}
    for index,result in zip(indices,candidates):
        if index not in expected or math.dist(result['xy'],expected[index])>20:raise ValueError('group_reference_mismatch')
    return dict(zip(indices,candidates))

def expected_point(reference,axis,index):
    """Search prior geometry; every returned measurement still needs optical evidence."""
    if not reference:return None
    points=sorted(reference.get(axis,[]),key=lambda p:p['index'])
    if len(points)<2:return None
    exact=next((p['xy'] for p in points if p['index']==index),None)
    if exact is not None:return exact
    pairs=list(zip(points,points[1:]))
    pair=next(((a,b) for a,b in pairs if a['index']<index<b['index']),None)
    if pair is None:
        if index==points[0]['index']-1:pair=pairs[0]
        elif index==points[-1]['index']+1:pair=pairs[-1]
        else:return None
    a,b=pair;gap=b['index']-a['index']
    if gap>3:return None
    f=(index-a['index'])/gap
    xy=[a['xy'][n]+f*(b['xy'][n]-a['xy'][n]) for n in (0,1)]
    return xy if 12<xy[0]<1908 and 12<xy[1]<1068 else None


def measure_layout(lights,snapshot,output,reference=None):
    import math
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    black=[(0,0,0)]*60;started=time.monotonic();captures=0;grouped=0;fallback=0
    calibration=dict(horizontal=[],vertical=[],missing=[],image_size=[1920,1080],camera='0')
    def capture():
        nonlocal captures
        data,info=snapshot(time.monotonic()+.05);captures+=1
        if info['device']!='0':raise ValueError('calibration_source_mismatch')
        return data
    try:
        for axis,indices in [('horizontal',list(range(30,44))),('vertical',list(range(29,20,-1)))]:
            results={}
            # Fast refresh only for an already measured, unchanged installation.
            if reference and reference.get('image_size')==[1920,1080] and reference.get('camera')=='0':
                lights.show(SHELF_LED_CHANNEL,black,brightness=.10);off=capture()
                for phase in range(4):
                    members=indices[phase::4]
                    if not members:continue
                    pixels=black.copy()
                    for index in members:pixels[index]=(255,0,0)
                    lights.show(SHELF_LED_CHANNEL,pixels,brightness=.10);on=capture()
                    (output/(axis+'-group-'+str(phase)+'.jpg')).write_bytes(on)
                    try:results.update(grouped_markers(off,on,axis,members,reference));grouped+=1
                    except ValueError as error:
                        if str(error)=='calibration_source_mismatch':raise
                        fallback+=len(members)
            for index in indices:
                result=results.get(index)
                if result is None:
                    lights.show(SHELF_LED_CHANNEL,black,brightness=.10);off=capture()
                    pixels=black.copy();pixels[index]=(255,0,0)
                    lights.show(SHELF_LED_CHANNEL,pixels,brightness=.10);on=capture()
                    expected=expected_point(reference,axis,index)
                    result=marker(off,on,expected)
                    if expected is not None and result.get('matched'):
                        result.update(xy=result['local_xy'],peak=result['local_peak'],method=result['local_method'],
                                      guided_by_reference=True)
                    (output/f'measurement-{index+1}.json').write_text(json.dumps(result,indent=2))
                    if index in (30,29):
                        (output/f'marker-{index+1}.jpg').write_bytes(on);(output/f'reference-{index+1}.jpg').write_bytes(off)
                xy=result['xy'];good=result['peak']>=15 and 12<xy[0]<1908 and 12<xy[1]<1068
                good=good and not any(math.dist(xy,p['xy'])<35 for ax in ('horizontal','vertical') for p in calibration[ax])
                previous=calibration[axis][-1:]
                if previous:good=good and (xy[0]>previous[0]['xy'][0]+35 if axis=='horizontal' else xy[1]<previous[0]['xy'][1]-35)
                if good:calibration[axis].append(dict(index=index,xy=xy,signal=result['peak'],marker_method=result['method'],red_halo_xy=result['red_halo_xy']))
                else:calibration['missing'].append(index)
                (output/'progress.json').write_text(json.dumps(dict(axis=axis,physical=index+1,accepted=good,calibration=calibration),indent=2))
        if len(calibration['horizontal'])<8 or len(calibration['vertical'])<5:raise ValueError('insufficient_calibration')
        calibration.update(measured_seconds=time.monotonic()-started,capture_count=captures,accepted_groups=grouped,fallback_pixels=fallback)
        (output/'calibration.json').write_text(json.dumps(calibration,indent=2));return calibration
    finally:lights.show(SHELF_LED_CHANNEL,black,brightness=.10)
