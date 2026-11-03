"""Experimental flat-book extent from long, collinear upper/lower seams."""
import numpy as np


def _band_extent(pts, anchors, lab):
    """Follow both seams past fragmented line segments, then locate end caps.

    Cover colour changes alone cannot terminate a spine: use paired boundary
    support and observable background beyond the band. No OCR text or book
    catalogue is used to choose the extent.
    """
    h,w=lab.shape[:2];xs=np.arange(w);cx=float(pts[:,0].mean())
    top,bottom=anchors
    thickness=(bottom[0]-top[0])*cx+bottom[1]-top[1]
    if thickness<10:return None
    colours=lab.astype(float)
    strengths=[]
    for m,b,*_ in anchors:
        y=np.rint(m*xs+b).astype(int)
        samples=lambda offsets:np.median([colours[np.clip(y+d,0,h-1),xs] for d in offsets],axis=0)
        above=samples((-5,-4,-3));below=samples((3,4,5));centre=samples((-1,0,1))
        # White books can meet along a dark shadow ridge while their cover
        # colours on either side are almost identical.
        strength=np.maximum.reduce([np.linalg.norm(above-below,axis=1),
            np.linalg.norm(centre-above,axis=1),np.linalg.norm(centre-below,axis=1)])
        strengths.append(np.median(np.lib.stride_tricks.sliding_window_view(np.pad(strength,(5,5),mode='edge'),11),axis=1))
    lo,hi=int(pts[:,0].min()),int(pts[:,0].max())
    reference=min(float(np.median(s[lo:hi+1])) for s in strengths)
    if reference<12:return None
    threshold=max(8,min(18,reference*.22))
    supported=np.minimum(*strengths)>=threshold
    if float(supported[lo:hi+1].mean())<.6:return None
    gap=max(12,int(thickness*.45))
    ends=[]
    for origin,step in ((lo,-1),(hi,1)):
        last=origin;missing=0
        for x in range(origin,w if step>0 else -1,step):
            if supported[x]:last=x;missing=0
            else:missing+=1
            if missing>=gap:break
        else:return None  # No observable background beyond this end.
        ends.append(last)
    left,right=ends
    if left>=lo or right<=hi:return None
    # A curved cap may stop before a neighbouring book's seam does. Require a
    # transition across most of the interior rows, close to the seam endpoint.
    fractions=np.linspace(.2,.8,15)
    ys=np.array([top[0]*xs+top[1]+f*((bottom[0]-top[0])*xs+bottom[1]-top[1]) for f in fractions])
    profile=colours[np.clip(np.rint(ys).astype(int),0,h-1),xs[None,:]]
    score=np.pad(np.median(np.linalg.norm(profile[:,6:]-profile[:,:-6],axis=2),axis=0),(3,3))
    reach=int(max(12,min(w*.04,thickness)))
    for side,current in enumerate((left,right)):
        a=max(3,current-reach);b=min(w-3,current+reach+1)
        if side==0:b=min(b,lo-3)
        else:a=max(a,hi+3)
        if b>a and float(score[a:b].max())>15:
            end=a+int(np.argmax(score[a:b]))
            if side==0:left=end
            else:right=end
    return left,right,dict(method='paired_seam_continuation',edge_threshold=threshold,
                           reference_strength=reference,observed_ends=ends,
                           end_cap_strength=[float(score[left]),float(score[right])])


def _refine_truncated_seam(pts,anchors,lab,continued):
    """Recheck a locally fitted slope only when another observed seam runs farther."""
    if continued is None:return anchors,continued
    cx=float(pts[:,0].mean());top,bottom=anchors
    thickness=(bottom[0]-top[0])*cx+bottom[1]-top[1]
    known_right=max(a[3] for a in anchors)
    if known_right-continued[1]<=max(20,thickness*.5):return anchors,continued
    candidates=[]
    for side in (0,1):
        source,other=anchors[side],anchors[1-side]
        for fraction in (.25,.5,.75):
            slope=source[0]+fraction*(other[0]-source[0])
            if abs(slope-source[0])>.03:continue
            revised=list(anchors)
            revised[side]=(slope,source[0]*cx+source[1]-slope*cx,*source[2:])
            result=_band_extent(pts,revised,lab)
            if result is None:continue
            left,right,audit=result
            if (right<known_right-thickness*.25 or right>known_right+max(35,thickness)
                or right-continued[1]<thickness*.5 or abs(left-continued[0])>thickness*.5
                or audit['end_cap_strength'][1]<=15):continue
            candidates.append((right,audit['end_cap_strength'][1],revised,result))
    if not candidates:return anchors,continued
    _,_,revised,result=max(candidates,key=lambda c:(c[0],c[1]))
    result[2]['slope_refinement']=dict(original_seams=anchors,refined_seams=revised,
        original_right=continued[1],independent_seam_end=known_right,
        method='bounded_slope_recheck_with_observed_end_cap')
    return revised,result


def restore_flat_extent(points, box, polygon, horizontal_lines, image_shape, lab=None):
    h,w=image_shape[:2]
    pts=np.asarray(points,dtype=float);cx=float(pts[:,0].mean())
    candidates=[]
    for line in horizontal_lines:
        x1,y1,x2,y2=map(float,line)
        if abs(x2-x1)<max(30,w*.025):
            continue
        m=(y2-y1)/(x2-x1);b=y1-m*x1
        overlap=max(0,min(max(x1,x2),pts[:,0].max())-max(min(x1,x2),pts[:,0].min()))
        candidates.append((m,b,min(x1,x2),max(x1,x2),overlap))
    anchors=[]
    for side in (0,1):
        boundary=float(np.mean(pts[:2,1]) if side==0 else np.mean(pts[2:,1]))
        eligible=[c for c in candidates if c[4]>=max(25,np.ptp(pts[:,0])*.18)
                  and (boundary-h*.12<c[0]*cx+c[1]<boundary-3 if side==0
                       else boundary+3<c[0]*cx+c[1]<boundary+h*.12)]
        # A closer crossing edge from another object is not the opposite seam.
        if anchors:eligible=[c for c in eligible if abs(c[0]-anchors[0][0])<=.035]
        if not eligible:
            return box,polygon,dict(status='insufficient_seams')
        # Closest supported seam outside the title; avoid another book layer.
        anchor=min(eligible,key=lambda c:abs(c[0]*cx+c[1]-boundary))
        group=[c for c in candidates if abs(c[0]-anchor[0])<.025
               and max(abs((c[0]-anchor[0])*x+c[1]-anchor[1]) for x in (c[2],c[3]))<6]
        xy=np.asarray([(x,c[0]*x+c[1]) for c in group for x in (c[2],c[3])])
        m,b=np.polyfit(xy[:,0],xy[:,1],1)
        anchors.append((m,b,min(c[2] for c in group),max(c[3] for c in group)))
    top,bottom=anchors
    thickness=(bottom[0]-top[0])*cx+bottom[1]-top[1]
    if thickness<max(10,np.ptp(pts[:,1])*.65):
        return box,polygon,dict(status='invalid_band')
    # Both seams must agree on the end; internal cover colour changes are not ends.
    continued=_band_extent(pts,anchors,lab) if lab is not None else None
    if lab is not None:
        anchors,continued=_refine_truncated_seam(pts,anchors,lab,continued)
        top,bottom=anchors
    if continued is None and any(abs(top[i]-bottom[i])>max(35,thickness*1.3) for i in (2,3)):
        return box,polygon,dict(status='end_disagreement',seams=anchors)
    left=max(0,int(round((top[2]+bottom[2])/2)))
    # The longest supported seam retains a rounded end cap when its opposite
    # seam stops early. Agreement above still bounds how far it may extend.
    right=min(w-1,int(round(max(top[3],bottom[3]))))
    if continued is not None:
        left,right,continuation_audit=continued
    if lab is not None and continued is None:
        # An end cap may curve inward at the seam endpoints. Check the interior
        # band transition nearby; require a change across many rows, not a letter.
        xs=np.arange(w)
        fractions=np.linspace(.15,.85,15)
        ys=np.asarray([top[0]*xs+top[1]+f*((bottom[0]-top[0])*xs+bottom[1]-top[1]) for f in fractions])
        ys=np.clip(np.rint(ys).astype(int),0,h-1)
        profile=lab[ys,xs[None,:]].astype(float)
        score=np.median(np.linalg.norm(profile[:,6:]-profile[:,:-6],axis=2),axis=0)
        score=np.pad(score,(3,3))
        for side,current in ((0,left),):
            reach=int(max(12,min(w*.045,thickness*.6)))
            lo=max(3,current-reach);hi=min(w-3,current+reach+1)
            if side==0: hi=min(hi,int(pts[:,0].min())-3)
            else: lo=max(lo,int(pts[:,0].max())+3)
            if hi>lo and score[lo:hi].max()>15:
                end=lo+int(np.argmax(score[lo:hi]))
                if side==0: left=end
                else: right=end
    if left>pts[:,0].min()+5 or right<pts[:,0].max()-5:
        return box,polygon,dict(status='cuts_title')
    poly=[[x,int(round(np.clip(m*x+b,0,h-1)))] for x,m,b in
          ((left,top[0],top[1]),(right,top[0],top[1]),(right,bottom[0],bottom[1]),(left,bottom[0],bottom[1]))]
    return [min(p[0] for p in poly),min(p[1] for p in poly),max(p[0] for p in poly),max(p[1] for p in poly)],poly,dict(status='seam_extent',seams=anchors,**(dict(continuation=continuation_audit) if continued is not None else {}))
