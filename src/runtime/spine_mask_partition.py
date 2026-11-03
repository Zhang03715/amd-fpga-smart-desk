"""Image-edge watershed proposals for masks containing neighbouring OCR text.

Splitting does not imply acceptance; use the unchanged mask/geometry validator.
No labels or per-photo coordinates are read.
"""
import cv2
import numpy as np


def extension_evidence(baseline,candidate):
    """Require an almost-contained baseline and length gain, not width gain."""
    base=np.column_stack(np.where(baseline)[::-1]).astype(float)
    new=np.column_stack(np.where(candidate)[::-1]).astype(float)
    if len(base)<3 or len(new)<3:
        return {'eligible_extension':False,'reason':'insufficient_pixels'}
    _,vectors=np.linalg.eigh(np.cov(base.T));axis=vectors[:,-1]
    normal=np.asarray([-axis[1],axis[0]])
    project=lambda points,direction:points[:,0]*direction[0]+points[:,1]*direction[1]
    length=max(1.,np.ptp(project(base,axis)));width=max(1.,np.ptp(project(base,normal)))
    coverage=float(np.count_nonzero(baseline&candidate)/max(1,np.count_nonzero(baseline)))
    length_ratio=float(np.ptp(project(new,axis))/length)
    width_ratio=float(np.ptp(project(new,normal))/width)
    addition=float((np.ptp(project(new,axis))-length)/width)
    return dict(baseline_coverage=coverage,length_ratio=length_ratio,width_ratio=width_ratio,
                added_length_in_body_widths=addition,
                eligible_extension=coverage>=.95 and length_ratio>=1.05 and width_ratio<=1.15 and addition>=.5)


def extend_quad_ends(baseline_quad,proposed_quad,title_boxes=(),neighbour_boxes=()):
    """Keep the old cap when only the opposite end has extension evidence."""
    original=np.asarray(baseline_quad,np.float32)
    proposal=np.asarray(proposed_quad,np.float32)
    _,vectors=np.linalg.eigh(np.cov(original.T));axis=vectors[:,-1]
    normal=np.asarray([-axis[1],axis[0]])
    def ordered(quad):
        indices=np.argsort(quad@axis)
        low=quad[indices[:2]];high=quad[indices[2:]]
        low=low[np.argsort(low@normal)];high=high[np.argsort(high@normal)]
        return np.asarray([low[0],low[1],high[1],high[0]],np.float32)
    old,new=ordered(original),ordered(proposal)
    width=max(1.,np.ptp(old@normal))
    result=old.copy()
    if (new[:2]@axis).mean()<(old[:2]@axis).mean()-width*.25:
        result[:2]=new[:2]
    if (new[2:]@axis).mean()>(old[2:]@axis).mean()+width*.25:
        result[2:]=new[2:]
    if not cv2.isContourConvex(result.reshape(-1,1,2)):
        return None,{'reason':'nonconvex_extension_quad'}
    for boxes,minimum,neighbour in [(title_boxes,.70,False),(neighbour_boxes,.15,True)]:
        for box in boxes:
            hull=cv2.convexHull(np.asarray(box,np.float32).reshape(-1,1,2))
            area=cv2.contourArea(hull)
            overlap,_=cv2.intersectConvexConvex(result,hull)
            fraction=overlap/max(1.,area)
            if (neighbour and fraction>minimum) or (not neighbour and fraction<minimum):
                return None,{'reason':'extension_quad_text_conflict'}
            if neighbour and cv2.pointPolygonTest(result,tuple(map(float,hull.reshape(-1,2).mean(axis=0))),False)>=0:
                return None,{'reason':'extension_quad_crosses_neighbour_center'}
    return np.rint(result).astype(int),{'reason':'only_supported_ends_extended'}


def partition_neighbour_mask(image,mask,points,labels,title_boxes,neighbour_boxes,*,foreground_seed=None,
                              expanded_neighbour_seeds=False,crop_to_mask=False):
    mask=np.asarray(mask,bool)
    audit={'method':'ocr_seeded_image_watershed','proposed':False,
           'neighbour_seed_scale':.75 if expanded_neighbour_seeds else .65}
    if image.shape[:2]!=mask.shape:
        audit['reason']='image_mask_shape_mismatch'
        return None,audit
    if crop_to_mask:
        yy,xx=np.where(mask)
        if not len(xx):
            audit['reason']='empty_mask'
            return None,audit
        h,w=mask.shape
        x0,y0=max(0,int(xx.min())-3),max(0,int(yy.min())-3)
        x1,y1=min(w,int(xx.max())+4),min(h,int(yy.max())+4)
        origin=np.asarray([x0,y0])
        local_points=np.asarray(points)-origin
        labels=np.asarray(labels)
        inside=(local_points[:,0]>=0)&(local_points[:,0]<x1-x0)&(local_points[:,1]>=0)&(local_points[:,1]<y1-y0)
        if np.any((labels==1)&~inside):
            audit['reason']='positive_seed_outside_mask_roi'
            return None,audit
        local,detail=partition_neighbour_mask(image[y0:y1,x0:x1],mask[y0:y1,x0:x1],
            local_points[inside],labels[inside],[np.asarray(b)-origin for b in title_boxes],
            [np.asarray(b)-origin for b in neighbour_boxes],
            foreground_seed=None if foreground_seed is None else foreground_seed[y0:y1,x0:x1],
            expanded_neighbour_seeds=expanded_neighbour_seeds,crop_to_mask=False)
        detail.update(roi_box=[x0,y0,x1,y1],input_shape=[h,w],working_shape=[y1-y0,x1-x0])
        if local is None:
            return None,detail
        result=np.zeros(mask.shape,bool);result[y0:y1,x0:x1]=local
        return result,detail
    markers=np.ones(mask.shape,np.int32)
    markers[mask]=0
    protected_text=np.zeros(mask.shape,bool)
    reassigned=0
    if foreground_seed is not None:
        if foreground_seed.shape!=mask.shape:
            audit['reason']='foreground_seed_shape_mismatch'
            return None,audit
        seed=cv2.erode(np.asarray(foreground_seed,np.uint8),np.ones((3,3),np.uint8))>0
        markers[seed&mask]=2
    def seed_polygon(box,label):
        nonlocal reassigned
        box=np.asarray(box,np.float32)
        center=box.mean(axis=0)
        scale=.75 if expanded_neighbour_seeds and label>2 else .65
        polygon=center+(box-center)*scale
        seed=np.zeros(mask.shape,np.uint8)
        cv2.fillConvexPoly(seed,np.rint(polygon).astype(np.int32),1)
        active=(seed>0)&mask
        conflicts=active&(markers>1)&(markers!=label)
        if expanded_neighbour_seeds and label>2:
            # The baseline mask is a prior, not OCR ground truth. Its border
            # may be reassigned, but an actual current-title seed may not.
            forbidden=conflicts&((markers!=2)|protected_text)
            if np.any(forbidden):
                return False
            reassigned+=int(np.count_nonzero(conflicts))
        elif np.any(conflicts):
            return False
        markers[active]=label
        if label==2:
            protected_text[active]=True
        return True
    for box in title_boxes:
        if not seed_polygon(box,2):
            audit['reason']='conflicting_ocr_seeds'
            return None,audit
    neighbour_count=0
    for label,box in enumerate(neighbour_boxes,3):
        before=np.count_nonzero(markers==label)
        if not seed_polygon(box,label):
            audit['reason']='conflicting_ocr_seeds'
            return None,audit
        if np.count_nonzero(markers==label)>before:
            neighbour_count+=1
    xy=np.rint(points).astype(int)
    for point,label in zip(xy,labels):
        x,y=point
        if not (0<=x<mask.shape[1] and 0<=y<mask.shape[0]):
            audit['reason']='prompt_outside_frame'
            return None,audit
        if label==1:
            if not mask[y,x] or markers[y,x]>2:
                audit['reason']='positive_seed_conflict'
                return None,audit
            markers[y,x]=2
    if not neighbour_count:
        audit['reason']='no_neighbour_text_inside_mask'
        return None,audit
    # Background is fixed outside the predicted mask. The watershed itself
    # follows image gradients, not nearest-text Euclidean Voronoi boundaries.
    cv2.watershed(image,markers)
    proposed=(markers==2)&mask
    audit.update(proposed=True,reason='requires_full_revalidation',
                 original_area=int(mask.sum()),partition_area=int(proposed.sum()),
                 neighbour_seed_regions=neighbour_count,
                 reassigned_foreground_seed_pixels=reassigned,
                 expanded_neighbour_seeds=expanded_neighbour_seeds)
    return proposed,audit
