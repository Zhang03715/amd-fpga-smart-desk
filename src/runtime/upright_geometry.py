"""Experimental perspective-aware geometry; no new OCR inference or catalogue."""
from copy import deepcopy
import cv2
import numpy as np
from spine_geometry import spine_edges, refine_sides, refine_ends


def supported_endcaps(edges, title, box, polygon=None, detrend=False):
    """Prefer width-spanning caps; a bottom must lead into surrounding shelf.

    Quietness is measured through a deep interior band to reject a white
    call-number label. Adjacent taller books must not contaminate that band.
    """
    vertical, horizontal, lab = edges
    h, w = lab.shape[:2]
    left, old_top, right, old_bottom = box
    width = right-left
    tx1, ty1, tx2, ty2 = title
    upper, lower, side_starts = [], [], []
    center_y = (ty1+ty2)/2
    for x1, y1, x2, y2 in vertical:
        if abs(y2-y1) < max(80, (ty2-ty1)*.5):
            continue
        if not min(y1,y2) <= center_y <= max(y1,y2):
            continue
        x = x1+(x2-x1)*(center_y-y1)/(y2-y1)
        if min(abs(x-left),abs(x-right)) < max(6,width*.15):
            side_starts.append(float(min(y1,y2)))
    # Long cap edges can be fragmented by wear or perspective. Also propose
    # transitions supported across the interior width, not just an LSD line.
    xa, xb = max(0,int(left+width*.15)), min(w,int(right-width*.15))
    strip = lab[:,xa:xb].astype(float)
    if polygon is not None and xb-xa>=8:
        corners=np.asarray(polygon,float)
        ys=np.arange(h,dtype=float)
        def project(first,last):
            return first[0]+(last[0]-first[0])*(ys-first[1])/max(1.,last[1]-first[1])
        lx,rx=project(corners[0],corners[3]),project(corners[1],corners[2])
        xs=lx[:,None]+(rx-lx)[:,None]*np.linspace(.15,.85,xb-xa)[None,:]
        strip=cv2.remap(lab.astype(np.float32),xs.astype(np.float32),
                       np.broadcast_to(ys[:,None],xs.shape).astype(np.float32),
                       cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(float)
    row_candidates = []
    if xb-xa >= 8:
        delta = np.linalg.norm(strip[6:]-strip[:-6],axis=2)
        strength = np.pad(np.median(delta,axis=1),(3,3))
        coverage = np.pad(np.mean(delta>8,axis=1),(3,3))
        local = cv2.dilate(strength.reshape(-1,1),np.ones((11,1),np.uint8)).ravel()
        row_candidates = np.flatnonzero((strength>=local-1e-6)&(strength>10)&(coverage>=.70)).tolist()
    candidates = [(float((y1+y2)/2),min(max(x1,x2),right)-max(min(x1,x2),left))
                  for x1,y1,x2,y2 in horizontal]
    candidates += [(float(y),width) for y in row_candidates]
    quiet_upper = []
    for y,overlap in candidates:
        if overlap < width*.70:
            continue
        if 1 < y < ty1-4:
            upper.append(y)
            previous = strip[max(0,int(y)-max(20,int(h*.025))):int(y)-4]
            following = strip[int(y)+4:min(h,int(y)+15)]
            if previous.size and following.size:
                background = np.median(previous.reshape(-1,3),axis=0)
                spread = np.percentile(np.linalg.norm(previous-background,axis=2),85)
                change = np.linalg.norm(np.median(following.reshape(-1,3),axis=0)-background)
                if spread<20 and change>10:
                    quiet_upper.append(y)
        if not ty2+4 < y < min(h-20,old_bottom+6):
            continue
        xa, xb = max(0,int(left+width*.15)), min(w,int(right-width*.15))
        quiet_depth = max(40,int(min(h*.12,width*.8)))
        patch = strip[int(y)+4:min(h,int(y)+quiet_depth)]
        before = strip[max(0,int(y)-15):int(y)-3]
        if not patch.size or not before.size:
            continue
        median = np.median(patch.reshape(-1,3),axis=0)
        # A shelf lit obliquely has a slow luminance gradient. Remove only a
        # bounded linear luminance trend; retain chroma and printed texture.
        quiet_patch=patch.copy()
        if detrend and len(patch)>10:
            luminance=np.median(patch[:,:,0],axis=1)
            axis=np.arange(len(patch),dtype=float)
            slope,intercept=np.polyfit(axis,luminance,1)
            if abs(slope)<.3:
                quiet_patch[:,:,0]-=(slope*(axis-axis.mean()))[:,None]
        quiet_median=np.median(quiet_patch.reshape(-1,3),axis=0)
        spread = np.percentile(np.linalg.norm(quiet_patch-quiet_median,axis=2),85)
        transition = np.linalg.norm(np.median(before.reshape(-1,3),axis=0)-median)
        if spread < 20 and transition > 10:
            lower.append(y)
    top, bottom = old_top, old_bottom
    if upper and side_starts:
        start = min(side_starts)
        supported = [y for y in upper if abs(y-start)<h*.015]
        if supported:
            top = int(round(min(supported,key=lambda y:abs(y-start))))
    if old_top==0 and quiet_upper:
        top = int(round(max(quiet_upper)))
    if lower:
        bottom = int(round(min(lower)))
    return [left,top,right,bottom], dict(top_cap_supported=top!=old_top,
                                       bottom_cap_supported=bool(lower),
                                       quiet_upper_candidates=sorted(set(round(y,1) for y in quiet_upper)))


def refine_upright_records(image, records, *, perspective_strip=False):
    edges = spine_edges(image)
    h, w = image.shape[:2]
    result = deepcopy(records)
    vertical_titles = sum(np.ptp(np.asarray(r['title_box']),axis=0)[1] >
                          2*np.ptp(np.asarray(r['title_box']),axis=0)[0] for r in records)
    upright_scene = vertical_titles >= 4 and vertical_titles >= len(records)*.5
    for record in result:
        points = np.asarray(record['title_box'], dtype=float)
        span = np.ptp(points, axis=0)
        if span[1] < span[0] * 2:
            # Frame-clipped vertical books often expose only a horizontal
            # header. Require two persistent local colour seams before
            # overriding the text-axis-derived horizontal physical box.
            if upright_scene and points[:,1].min() > h*.90 and span[0] > span[1]*1.2:
                containing = []
                for parent in records:
                    parent_points = np.asarray(parent['title_box'])
                    parent_span = np.ptp(parent_points,axis=0)
                    if parent_span[1] <= parent_span[0]*2:
                        continue
                    x1,y1,x2,y2 = parent['book_box']
                    if (points[:,0].min()>=x1-2 and points[:,0].max()<=x2+2
                            and points[:,1].min()>=y1-2 and points[:,1].max()<=y2+2):
                        containing.append(parent)
                if containing:
                    continue
                lo = max(0,int(points[:,1].min()-h*.08))
                lab = edges[2][lo:].astype(float)
                radius = max(2,int(w*.002))
                profile = np.median(np.linalg.norm(lab[:,2*radius:]-lab[:,:-2*radius],axis=2),axis=0)
                profile = np.pad(profile,(radius,radius))
                local = cv2.dilate(profile.reshape(1,-1),np.ones((1,max(9,int(w*.008))|1),np.uint8)).ravel()
                peaks = np.flatnonzero((profile>=local-1e-6)&(profile>8))
                left = [x for x in peaks if points[:,0].min()-w*.10 < x < points[:,0].min()-2]
                right = [x for x in peaks if points[:,0].max()+2 < x < points[:,0].max()+w*.10]
                if left and right:
                    xa,xb=int(max(left)),int(min(right))
                    if span[0] < xb-xa < max(span[0]*3,w*.12):
                        from hybrid_book_locator import vertical_extent
                        top,_ = vertical_extent(image,xa,xb,points[:,1].min(),points[:,1].max())
                        record['book_box']=[xa,top,xb,h-1]
                        record['spine_polygon']=[[xa,top],[xb,top],[xb,h-1],[xa,h-1]]
                        record['orientation']='upright'
                        record['visible_region_clipped']=True
                        record['boundary_method']='frame_clipped_persistent_colour_seams_experimental'
                        record['upright_geometry_audit']=dict(status='clipped_local_seams',bottom='outside_frame_unknown')
            continue
        title = (points[:, 0].min(), points[:, 1].min(), points[:, 0].max(), points[:, 1].max())
        tolerance = min(8., max(2., span[0] * .15))
        fit_audit={}
        box, polygon = refine_sides(edges[0], title, record['book_box'], image.shape,
                                    points, text_tolerance=tolerance, fit_audit=fit_audit)
        if polygon is None:
            record['upright_geometry_audit'] = dict(status='no_supported_side_fit')
            continue
        extent = refine_ends(edges, title, box)
        extent, caps = supported_endcaps(edges, title, extent,
                                         polygon=polygon if perspective_strip else None,
                                         detrend=perspective_strip)
        # Preserve the perspective side lines when adjusting the endpoints.
        old = np.asarray(polygon, float)
        corners = []
        for first, last, y in ((old[0], old[3], extent[1]), (old[1], old[2], extent[1]),
                               (old[1], old[2], extent[3]), (old[0], old[3], extent[3])):
            x = first[0] + (last[0] - first[0]) * (y-first[1]) / max(1., last[1]-first[1])
            corners.append([int(round(np.clip(x, 0, w-1))), int(y)])
        record['book_box'] = [min(p[0] for p in corners), extent[1], max(p[0] for p in corners), extent[3]]
        record['spine_polygon'] = corners
        record['boundary_method'] = 'perspective_text_quad_sides_then_ends_experimental'
        record['upright_geometry_audit'] = dict(status='refined', text_tolerance=tolerance, **caps, **fit_audit)
    return result
