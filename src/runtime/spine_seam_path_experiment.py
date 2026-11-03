"""Offline continuous seam evidence; does not infer book identity or endcaps."""
import cv2
import numpy as np


def supported_interior_endcap(samples, thickness, old_end):
    """Propose a cap before sustained loss of BOTH side seams; review only.

    Samples must be ordered, one per longitudinal pixel. No manual references.
    """
    needed=max(3,int(np.ceil(thickness*.5)))
    run=[]
    fade=None
    for sample in samples:
        if sample['position']<=old_end:
            continue
        if max(sample['side_strengths'])<12:
            if run and sample['position']!=run[-1]+1:
                run=[]
            run.append(sample['position'])
            if len(run)>=needed:
                fade=run[0]
                break
        else:
            run=[]
    if fade is None:
        return dict(status='no_sustained_paired_side_loss')
    candidates=[s for s in samples if max(old_end+thickness*.5,fade-thickness)<=s['position']<fade
                and s['transverse_support']>=.70 and s['transverse_median']>=12]
    if not candidates:
        return dict(status='no_supported_cap_before_side_loss',fade_start=fade)
    best=max(candidates,key=lambda s:s['transverse_median'])
    return dict(status='review_only_not_validated',endpoint=best['position'],fade_start=fade,
                cap=best,weak_run_required=needed,accepted_for_production=False)


def propose_interior_extension(image, polygon):
    """Extract paired evidence and propose a quad without annotations or IDs."""
    p=np.asarray(polygon,float)
    if p.shape!=(4,2) or not np.isfinite(p).all():
        return None,dict(status='invalid_polygon')
    h,w=image.shape[:2]
    vertical=np.ptp(p[:,1])>np.ptp(p[:,0])
    work=cv2.rotate(image,cv2.ROTATE_90_COUNTERCLOCKWISE) if vertical else image
    if vertical:
        p=np.column_stack([p[:,1],w-1-p[:,0]])
    ordered=p[np.argsort(p[:,0],kind='stable')]
    left=ordered[:2][np.argsort(ordered[:2,1])]
    right=ordered[2:][np.argsort(ordered[2:,1])]
    thickness=float(right[1,1]-right[0,1])
    old_end=float(right[:,0].max())
    if thickness<8 or right[:,0].mean()-left[:,0].mean()<2*thickness:
        return None,dict(status='weak_long_axis')
    if work.shape[1]-1-old_end<thickness:
        return None,dict(status='insufficient_room_for_end_evidence')
    traces=[trace_side(work,a,work.shape[1]-1,float((b[1]-a[1])/max(1.,b[0]-a[0])),thickness)
            for a,b in zip(left,right)]
    if any(not t['path'] for t in traces):
        return None,dict(status='missing_side_path',side_status=[t['status'] for t in traces])
    xs=np.arange(int(np.ceil(max(left[:,0])))+3,work.shape[1]-3)
    positions=[np.interp(xs,np.asarray(t['path'])[:,0],np.asarray(t['path'])[:,1]) for t in traces]
    strengths=[np.interp(xs,np.asarray(t['path'])[:,0],t['strengths']) for t in traces]
    lab=cv2.cvtColor(work,cv2.COLOR_BGR2LAB).astype(np.float32)
    samples=[]
    for k,x in enumerate(xs):
        lo=max(0,int(np.ceil(positions[0][k]+thickness*.15)))
        hi=min(work.shape[0],int(np.floor(positions[1][k]-thickness*.15)))
        if hi<=lo:
            continue
        delta=np.linalg.norm(lab[lo:hi,x+3]-lab[lo:hi,x-3],axis=1)
        samples.append(dict(position=int(x),side_strengths=[float(s[k]) for s in strengths],
                            transverse_support=float(np.mean(delta>=12)),transverse_median=float(np.median(delta))))
    audit=supported_interior_endcap(samples,thickness,old_end)
    if 'endpoint' not in audit:
        return None,audit
    end=audit['endpoint']
    end_sides=[float(np.interp(end,np.asarray(t['path'])[:,0],np.asarray(t['path'])[:,1])) for t in traces]
    if end_sides[1]-end_sides[0]<8:
        return None,dict(status='crossing_or_collapsed_side_paths')
    proposed=np.asarray([left[0],[end,end_sides[0]],[end,end_sides[1]],left[1]])
    if vertical:
        proposed=np.column_stack([w-1-proposed[:,1],proposed[:,0]])
    return np.rint(proposed).astype(np.int32),audit


def trace_side(image, start, end_x, slope, thickness):
    """Track one near-horizontal side in the old 18%-thickness corridor.

    Returns evidence, never an accepted boundary. A best path can still be wrong.
    """
    h,w=image.shape[:2]
    x0,y0=map(float,start)
    if not (0<=x0<w and 0<=y0<h and x0<end_x<w):
        return dict(status='invalid_or_clipped_start',path=[])
    lab=cv2.cvtColor(image,cv2.COLOR_BGR2LAB)
    xs=np.unique(np.r_[np.arange(int(x0),int(end_x)+1,8),int(end_x)])
    radius=max(6,int(round(thickness*.18)))
    expected=y0+slope*(xs-x0)
    if np.any((expected<0)|(expected>=h)):
        return dict(status='prior_exits_frame',path=[],exit_x=int(xs[np.flatnonzero((expected<0)|(expected>=h))[0]]))
    lows=np.maximum(3,np.floor(expected-radius).astype(int))
    highs=np.minimum(h-4,np.ceil(expected+radius).astype(int))
    if np.any(lows>highs):
        return dict(status='no_visible_corridor',path=[])
    positions=[np.arange(lo,hi+1) for lo,hi in zip(lows,highs)]
    strengths=[]
    for x,ys in zip(xs,positions):
        profile=np.median(lab[:,max(0,x-6):min(w,x+7)],axis=1).astype(np.float32)
        strengths.append(np.linalg.norm(profile[ys+3]-profile[ys-3],axis=1))
    # Cap strong text edges so a single black glyph cannot dominate the path.
    costs=-np.minimum(strengths[0]/12.,3.)
    parents=[]
    for k in range(1,len(xs)):
        displacement=positions[k][:,None]-positions[k-1][None,:]
        residual=np.abs(displacement-slope*(xs[k]-xs[k-1]))
        # At most one pixel of residual motion per four longitudinal pixels.
        transition=np.where(residual<=max(1.,(xs[k]-xs[k-1])*.25),
                            residual*.25,np.inf)
        total=costs[None,:]+transition
        parent=np.argmin(total,axis=1)
        costs=total[np.arange(len(parent)),parent]-np.minimum(strengths[k]/12.,3.)
        parents.append(parent)
    if not np.isfinite(costs).any():
        return dict(status='no_continuous_path',path=[])
    cursor=int(np.argmin(costs))
    indices=[cursor]
    for parent in reversed(parents):
        cursor=int(parent[cursor]);indices.append(cursor)
    indices.reverse()
    path=[[int(x),int(ys[i])] for x,ys,i in zip(xs,positions,indices)]
    values=[float(s[i]) for s,i in zip(strengths,indices)]
    weak=np.asarray(values)<12
    longest=run=0
    for value in weak:
        run=run+1 if value else 0
        longest=max(longest,run)
    return dict(status='diagnostic_path_only',path=path,strengths=values,
                supported_fraction=float(np.mean(~weak)),longest_weak_run_samples=longest,
                corridor_radius=radius,max_prior_displacement=float(max(abs(p[1]-y) for p,y in zip(path,expected))))


def propose_visible_extension(image, polygon):
    """Generic right/down extension diagnostic. No ownership or acceptance claim.

    Keeps the old opposite cap. Requires both sides to be observed up to their
    visible safe extent; frame-exiting tails retain their unverified prior.
    """
    p=np.asarray(polygon,float)
    if p.shape!=(4,2) or not np.isfinite(p).all():
        return None,dict(status='invalid_polygon')
    h,w=image.shape[:2]
    vertical=np.ptp(p[:,1])>np.ptp(p[:,0])
    work=cv2.rotate(image,cv2.ROTATE_90_COUNTERCLOCKWISE) if vertical else image
    if vertical:
        p=np.column_stack([p[:,1],w-1-p[:,0]])
    hh,ww=work.shape[:2]
    ordered=p[np.argsort(p[:,0],kind='stable')]
    left=ordered[:2][np.argsort(ordered[:2,1])]
    right=ordered[2:][np.argsort(ordered[2:,1])]
    length=float(right[:,0].mean()-left[:,0].mean())
    thickness=float(right[1,1]-right[0,1])
    if length<2*thickness or thickness<8:
        return None,dict(status='weak_long_axis')
    if ww-1-right[:,0].max()<16:
        return None,dict(status='already_at_frame')
    traces=[]
    tails=[]
    for a,b in zip(left,right):
        slope=float((b[1]-a[1])/max(1.,b[0]-a[0]))
        projected=float(a[1]+slope*(ww-1-a[0]))
        end=ww-1
        clipped=not 3<=projected<=hh-4
        if clipped:
            if abs(slope)<1e-8:
                return None,dict(status='side_without_visible_margin')
            target=hh-4 if slope>0 else 3
            end=min(end,int((target-a[1])/slope+a[0]))
        # Observe the existing long side too, before extrapolating a clipped tail.
        if end<=a[0]+8:
            return None,dict(status='insufficient_visible_side')
        trace=trace_side(work,a,end,slope,thickness)
        traces.append(trace)
        tails.append(dict(clipped=clipped,projected_end=[ww-1,projected],
                          unobserved_tail=clipped))
        if (trace.get('supported_fraction',0)<.95 or
                trace.get('longest_weak_run_samples',100)>2):
            return None,dict(status='insufficient_continuous_side_support',sides=traces,tails=tails)
    upper=traces[0]['path']
    lower=traces[1]['path']
    contour=np.asarray([*upper,tails[0]['projected_end'],tails[1]['projected_end'],*reversed(lower)],float)
    mask=np.zeros((hh,ww),np.uint8)
    cv2.fillPoly(mask,[np.rint(contour).astype(np.int32)],1)
    if vertical:
        mask=cv2.rotate(mask,cv2.ROTATE_90_CLOCKWISE)
    return mask.astype(bool),dict(status='review_only_not_validated',sides=traces,tails=tails,
                                  axis='vertical' if vertical else 'horizontal',
                                  physical_terminal_end='unknown_at_or_outside_frame',
                                  accepted_for_production=False)
