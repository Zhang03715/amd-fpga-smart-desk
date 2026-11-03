"""Offline MobileSAM CUDA proposals prompted only by saved OCR evidence.

No reference annotations or case-specific coordinates are read. SAM predicted
IoU is recorded as a model score, never reported as book/spine accuracy.
This program does not change service defaults or issue actuator commands.
"""
from copy import deepcopy
import cv2
import numpy as np


def contour_quad(contour):
    """Preserve a supported trapezoid rather than force parallel sides.

    Only a convex four-corner simplification with similar area is accepted.
    Irregular or incomplete masks retain the explicit rectangle fallback.
    """
    hull=cv2.convexHull(contour)
    area=cv2.contourArea(hull)
    perimeter=cv2.arcLength(hull,True)
    for fraction in (.005,.01,.015,.02,.025,.03,.04,.05):
        approx=cv2.approxPolyDP(hull,perimeter*fraction,True)
        if len(approx)==4 and cv2.isContourConvex(approx):
            ratio=cv2.contourArea(approx)/max(1.,area)
            if ratio>=.95:
                return approx.reshape(4,2).astype(np.float32),'convex_contour_quad'
    return cv2.boxPoints(cv2.minAreaRect(contour)),'minimum_rectangle_fallback'


def mask_side_quad(mask):
    """Fit two sides in PCA coordinates; reject weak width support.

    This estimates a visible mask envelope, not an anatomical/semantic edge.
    Quantile trimming suppresses isolated protrusions without reading labels.
    """
    y,x=np.where(mask)
    points=np.column_stack((x,y)).astype(float)
    if len(points)<64:
        return None
    center=points.mean(axis=0)
    _,vectors=np.linalg.eigh(np.cov((points-center).T))
    u=vectors[:,-1];v=np.asarray([-u[1],u[0]])
    t=(points-center)@u;s=(points-center)@v
    lo,hi=np.quantile(t,[.005,.995])
    if hi-lo<20:
        return None
    samples=[]
    edges=np.linspace(lo,hi,61)
    # Group pixels once instead of scanning the entire mask for each slice.
    # Stable sorting retains the old within-slice sample order, including
    # lower-inclusive and upper-exclusive membership at exact boundaries.
    bins=np.searchsorted(edges,t,side='right')-1
    order=np.argsort(bins,kind='stable')
    sorted_bins=bins[order]
    sorted_s=s[order]
    cuts=np.searchsorted(sorted_bins,np.arange(61))
    for index,(a,b) in enumerate(zip(edges[:-1],edges[1:])):
        values=sorted_s[cuts[index]:cuts[index+1]]
        if len(values)>=8:
            left,right=np.quantile(values,[.02,.98])
            samples.append(((a+b)/2,left,right))
    rows=np.asarray(samples)
    if len(rows)<40:
        return None
    widths=rows[:,2]-rows[:,1]
    supported=widths>=np.median(widths)*.65
    middle=supported&(rows[:,0]>lo+(hi-lo)*.10)&(rows[:,0]<hi-(hi-lo)*.10)
    if middle.sum()<24:
        return None
    fits=[]
    for column in (1,2):
        keep=middle.copy()
        for _ in range(3):
            fit=np.polyfit(rows[keep,0],rows[keep,column],1)
            residual=np.abs(rows[:,column]-np.polyval(fit,rows[:,0]))
            keep=middle&(residual<=max(2.,np.median(residual[middle])*2.5))
            if keep.sum()<16:
                return None
        fits.append(fit)
    ends=rows[supported,0]
    low,high=ends.min(),ends.max()
    quad=np.asarray([center+tt*u+np.polyval(fits[side],tt)*v
                     for tt,side in [(low,0),(low,1),(high,1),(high,0)]],np.float32)
    if not cv2.isContourConvex(quad.reshape(-1,1,2)):
        return None
    # A fitted quad must explain most of this mask, without inflating its area.
    raster=np.zeros(mask.shape,np.uint8)
    cv2.fillConvexPoly(raster,np.rint(quad).astype(np.int32),1)
    intersection=np.count_nonzero(mask&(raster>0))
    union=np.count_nonzero(mask|(raster>0))
    if intersection/max(1,union)<.85:
        return None
    return quad


def prompt_points(spine, regions, spines):
    title=np.asarray(regions[spine['representative_region_id']]['title_box'],float)
    center=title.mean(axis=0)
    _,vectors=np.linalg.eigh(np.cov((title-center).T))
    axis=vectors[:,-1]
    half=float(np.ptp(title@axis))*.32
    positives=np.asarray([center-half*axis,center,center+half*axis])
    neighbours=[]
    for other in spines:
        if other['group_id']==spine['group_id']:
            continue
        quad=np.asarray(regions[other['representative_region_id']]['title_box'],float)
        point=quad.mean(axis=0)
        neighbours.append((float(np.linalg.norm(point-center)),point))
    negatives=[p for _,p in sorted(neighbours,key=lambda item:item[0])[:6]]
    points=np.concatenate([positives,np.asarray(negatives).reshape(-1,2)])
    labels=np.asarray([1]*len(positives)+[0]*len(negatives),np.int32)
    return points.astype(np.float32),labels


def prompt_box(spine,regions,spines,image_shape):
    """Bound the prompt corridor by neighbouring text centre lines.

    A prompt box is guidance, not an asserted physical boundary. Perspective
    axis and relative text positions are computed per image, without labels.
    """
    title=np.asarray(regions[spine['representative_region_id']]['title_box'],float)
    center=title.mean(axis=0)
    _,vectors=np.linalg.eigh(np.cov((title-center).T))
    u=vectors[:,-1];v=np.asarray([-u[1],u[0]])
    current=float(center@v)
    distances=[]
    span=title@u
    for other in spines:
        if other['group_id']==spine['group_id']:
            continue
        quad=np.asarray(regions[other['representative_region_id']]['title_box'],float)
        other_span=quad@u
        overlap=min(span.max(),other_span.max())-max(span.min(),other_span.min())
        if overlap>min(np.ptp(span),np.ptp(other_span))*.25:
            distances.append(float(quad.mean(axis=0)@v))
    polygon=np.asarray(spine['spine_polygon'],float)
    lo,hi=float((polygon@v).min()),float((polygon@v).max())
    left=[x for x in distances if x<current-3]
    right=[x for x in distances if x>current+3]
    if left:
        lo=max(lo,(max(left)+current)/2)
    if right:
        hi=min(hi,(min(right)+current)/2)
    lo=min(lo,float((title@v).min())-2)
    hi=max(hi,float((title@v).max())+2)
    h,w=image_shape[:2]
    tlo=float((polygon@u).min())-h*.12
    thi=float((polygon@u).max())+h*.08
    corners=np.asarray([t*u+s*v for t in (tlo,thi) for s in (lo,hi)])
    return np.asarray([max(0,corners[:,0].min()),max(0,corners[:,1].min()),
                       min(w-1,corners[:,0].max()),min(h-1,corners[:,1].max())],np.float32)


def full_axis_prompt_box(box,title_box,image_shape):
    """Remove a truncated prior's length constraint for nearly upright/flat text.

    Only a separate model prompt is widened, never the returned physical quad.
    Preserve the short-axis corridor; oblique titles keep their original box.
    """
    title=np.asarray(title_box,float)
    _,vectors=np.linalg.eigh(np.cov((title-title.mean(axis=0)).T))
    axis=np.abs(vectors[:,-1])
    result=np.asarray(box,np.float32).copy()
    h,w=image_shape[:2]
    if axis[1]>=.98:
        result[[1,3]]=[0,h-1]
    elif axis[0]>=.98:
        result[[0,2]]=[0,w-1]
    return result


def validate_mask(mask, points, labels, title_box, excluded_title_boxes=(), member_title_boxes=(), *, image=None, edge_caps=False, proposed_quad=None):
    mask=np.asarray(mask,bool)
    if mask.ndim!=2:
        return None,dict(eligible=False,reason='invalid_mask')
    h,w=mask.shape
    points=np.asarray(points,float)
    if not np.isfinite(points).all():
        return None,dict(eligible=False,reason='invalid_prompt')
    xy=np.rint(points).astype(int)
    if np.any(xy[:,0]<0) or np.any(xy[:,0]>=w) or np.any(xy[:,1]<0) or np.any(xy[:,1]>=h):
        return None,dict(eligible=False,reason='prompt_outside_frame')
    n,components,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
    votes=components[xy[labels==1,1],xy[labels==1,0]]
    ids,counts=np.unique(votes[votes>0],return_counts=True)
    if not len(ids):
        return None,dict(eligible=False,reason='no_seed_component')
    selected=int(ids[np.argmax(counts)])
    component=components==selected
    if not np.all(component[xy[labels==1,1],xy[labels==1,0]]):
        return None,dict(eligible=False,reason='positive_seeds_disconnected')
    if np.any(component[xy[labels==0,1],xy[labels==0,0]]):
        return None,dict(eligible=False,reason='includes_neighbour_seed')
    title=np.asarray(title_box,np.float32)
    text_mask=np.zeros((h,w),np.uint8)
    cv2.fillConvexPoly(text_mask,np.rint(title).astype(np.int32),1)
    coverage=float(component[text_mask>0].mean()) if text_mask.any() else 0.
    area=int(component.sum())
    if coverage<.70:
        return None,dict(eligible=False,reason='insufficient_text_coverage',text_coverage=coverage)
    if area<max(32,cv2.contourArea(title)*1.25) or area>h*w*.35:
        return None,dict(eligible=False,reason='implausible_book_area',area=area)
    y,x=np.where(component)
    box=[int(x.min()),int(y.min()),int(x.max()),int(y.max())]
    contours,_=cv2.findContours(component.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    contour=max(contours,key=cv2.contourArea)
    fitted,fit_method=contour_quad(contour)
    side_quad=mask_side_quad(component)
    if side_quad is not None:
        fitted,fit_method=side_quad,'robust_mask_sides'
    if proposed_quad is not None:
        proposed=np.asarray(proposed_quad,np.float32)
        if (proposed.shape!=(4,2) or not np.isfinite(proposed).all()
                or not cv2.isContourConvex(proposed.reshape(-1,1,2))
                or cv2.contourArea(proposed)<16
                or np.any(proposed[:,0]<0) or np.any(proposed[:,0]>=w)
                or np.any(proposed[:,1]<0) or np.any(proposed[:,1]>=h)):
            return None,dict(eligible=False,reason='invalid_proposed_quad')
        raster=np.zeros((h,w),np.uint8)
        cv2.fillConvexPoly(raster,np.rint(proposed).astype(np.int32),1)
        union=np.count_nonzero((raster>0)|component)
        overlap=np.count_nonzero((raster>0)&component)/max(1,union)
        if overlap<.90:
            return None,dict(eligible=False,reason='proposed_quad_not_supported_by_mask',quad_mask_iou=float(overlap))
        fitted,fit_method=proposed,'explicit_mask_supported_quad_review_only'
    cap_audit=None
    if edge_caps:
        if image is None or image.shape[:2]!=mask.shape:
            raise ValueError('edge_caps requires the original image with matching mask dimensions')
        from spine_cap_edges import refine_supported_caps
        fitted,cap_audit=refine_supported_caps(image,component,fitted,[title,*member_title_boxes])
        if cap_audit['applied']:
            fit_method='silhouette_and_image_edge_caps'
    polygon=fitted.round().astype(int)
    polygon[:,0]=np.clip(polygon[:,0],0,w-1)
    polygon[:,1]=np.clip(polygon[:,1],0,h-1)
    mask_box=box.copy()
    if cap_audit is not None and cap_audit['applied']:
        box=[int(polygon[:,0].min()),int(polygon[:,1].min()),
             int(polygon[:,0].max()),int(polygon[:,1].max())]
    # A text-shaped fragment can cover the title yet leave most of the book
    # missing. Reject sparse masks; passing is still not physical acceptance.
    rectangle_area=max(1.,cv2.contourArea(polygon.astype(np.float32)))
    fill_ratio=area/rectangle_area
    if fill_ratio<.75:
        return None,dict(eligible=False,reason='sparse_text_fragment',rectangle_fill=fill_ratio)
    for member in member_title_boxes:
        member_mask=np.zeros((h,w),np.uint8)
        cv2.fillConvexPoly(member_mask,np.rint(member).astype(np.int32),1)
        if member_mask.any() and component[member_mask>0].mean()<.70:
            return None,dict(eligible=False,reason='misses_group_member_text')
    for other in excluded_title_boxes:
        other=np.asarray(other,np.float32)
        excluded=np.zeros((h,w),np.uint8)
        cv2.fillConvexPoly(excluded,np.rint(other).astype(np.int32),1)
        if excluded.any() and component[excluded>0].mean()>.15:
            return None,dict(eligible=False,reason='includes_neighbour_text')
        # A convex fit can bridge a notch/hole that the mask correctly excluded.
        # Checking only the neighbour centre misses partial title incursions.
        other_hull=cv2.convexHull(other.reshape(-1,1,2))
        other_area=cv2.contourArea(other_hull)
        overlap,_=cv2.intersectConvexConvex(polygon.astype(np.float32),other_hull)
        if other_area>0 and overlap/other_area>.15:
            return None,dict(eligible=False,reason='fitted_quad_overlaps_neighbour_text',
                             neighbour_text_overlap=float(overlap/other_area))
        other_center=other.mean(axis=0)
        if cv2.pointPolygonTest(polygon.astype(np.float32),tuple(map(float,other_center)),False)>=0:
            return None,dict(eligible=False,reason='fitted_quad_crosses_neighbour_text')
    return component,dict(eligible=True,reason='prompt_and_geometry_checks_passed_not_visual_acceptance',
                          text_coverage=coverage,area=area,book_box=box,quad_fit_method=fit_method,
                          mask_box=mask_box,
                          cap_refinement=cap_audit,
                          polygon=polygon.tolist(),mask_contour=cv2.approxPolyDP(contour,
                          max(1.,cv2.arcLength(contour,True)*.002),True).reshape(-1,2).tolist())


def prior_axis_points(spine,image_shape,*,full_extent=False):
    """Experimental prior-interior anchors, never asserted physical corners."""
    polygon=np.asarray(spine['spine_polygon'],float)
    center=polygon.mean(axis=0)
    _,vectors=np.linalg.eigh(np.cov((polygon-center).T));axis=vectors[:,-1]
    projections=(polygon-center)@axis
    lo,hi=float(projections.min()),float(projections.max())
    h,w=image_shape[:2]
    if full_extent:
        lo,hi=-float('inf'),float('inf')
        for dimension,size in enumerate((w,h)):
            if abs(axis[dimension])>1e-8:
                limits=sorted(((0-center[dimension])/axis[dimension],(size-1-center[dimension])/axis[dimension]))
                lo,hi=max(lo,limits[0]),min(hi,limits[1])
    anchors=np.asarray([center+(lo+(hi-lo)*fraction)*axis for fraction in (.10,.90)])
    anchors[:,0]=np.clip(anchors[:,0],0,w-1)
    anchors[:,1]=np.clip(anchors[:,1],0,h-1)
    return anchors.astype(np.float32)


def propose_spines(image, grouped, predictor, *, synchronize=lambda:None, full_axis_prompts=False, edge_caps=False,
                   candidate_sink=None, prior_axis_prompts=False, evidence_negative_prompts=False):
    import time
    result=deepcopy(grouped)
    for spine in result['spines']:
        spine['geometry_quality']={'status':'review_required',
                                   'reason':'offline_sam_candidate_not_visual_acceptance'}
    started=time.perf_counter()
    predictor.set_image(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
    synchronize()
    embedding_seconds=time.perf_counter()-started
    proposals=[]
    masks={}
    for spine in result['spines']:
        points,labels=prompt_points(spine,result['regions'],result['spines'])
        record=result['regions'][spine['representative_region_id']]
        prompt_keep=np.ones(len(labels),dtype=bool)
        relation_audit=[]
        if evidence_negative_prompts:
            from spine_prompt_relations_experiment import text_band_relation
            for index in np.flatnonzero(labels==0):
                others=[other for other in result['spines'] if other['group_id']!=spine['group_id']
                        and np.linalg.norm(np.asarray(result['regions'][other['representative_region_id']]['title_box']).mean(axis=0)-points[index])<.01]
                evidence=[text_band_relation(record['title_box'],result['regions'][other['representative_region_id']]['title_box']) for other in others]
                prompt_keep[index]=bool(evidence) and all(e['relation']=='separated_text_bands' for e in evidence)
                relation_audit.append(dict(point_index=int(index),used_for_inference=bool(prompt_keep[index]),evidence=evidence))
        excluded=[result['regions'][other['representative_region_id']]['title_box']
                  for other in result['spines'] if other['group_id']!=spine['group_id']]
        members=[result['regions'][idx]['title_box'] for idx in spine['region_ids']]
        # The saved group supplies identity; mask prediction, not manual box
        # annotations, estimates the visible object extent.
        runs=[]
        prompt_started=time.perf_counter()
        box=prompt_box(spine,result['regions'],result['spines'],image.shape)
        full_box=full_axis_prompt_box(box,record['title_box'],image.shape)
        modes=[('points',None),('points_box',box),('box_only',box)]
        if full_axis_prompts and not np.array_equal(full_box,box):
            modes.append(('full_axis_box',full_box))
        if prior_axis_prompts:
            modes.append(('prior_axis_points',box))
            modes.append(('full_axis_points',full_box))
        for mode,box_prompt in modes:
            # A title prompt can select a printed panel instead of the book.
            # Independently prompt the corridor, but retain the same positive
            # and neighbour checks when validating the resulting object.
            box_only=mode in ('box_only','full_axis_box')
            inference_points,inference_labels=points,labels
            if mode in ('prior_axis_points','full_axis_points'):
                inference_points=np.concatenate([points,prior_axis_points(spine,image.shape,full_extent=mode=='full_axis_points')])
                inference_labels=np.concatenate([labels,np.ones(2,np.int32)])
            model_keep=np.concatenate([prompt_keep,np.ones(len(inference_labels)-len(labels),dtype=bool)])
            predictions,scores,_=predictor.predict(point_coords=None if box_only else inference_points[model_keep],
                                                   point_labels=None if box_only else inference_labels[model_keep],
                                                   box=box_prompt,multimask_output=True)
            synchronize()
            for candidate_index,(predicted,score) in enumerate(zip(predictions,scores)):
                mask,audit=validate_mask(predicted,inference_points,inference_labels,record['title_box'],excluded,members,
                                         image=image,edge_caps=edge_caps)
                audit.update(prompt_mode=mode,model_predicted_iou=float(score),
                             candidate_index=candidate_index,
                             extra_prior_points=prior_axis_points(spine,image.shape,full_extent=mode=='full_axis_points').tolist()
                                  if mode in ('prior_axis_points','full_axis_points') else None,
                             validation_points=inference_points.tolist() if mode in ('prior_axis_points','full_axis_points') else None,
                             validation_labels=inference_labels.tolist() if mode in ('prior_axis_points','full_axis_points') else None,
                             score_semantics='model_internal_score_not_measured_accuracy')
                if candidate_sink is not None:
                    audit['saved_mask']=candidate_sink(spine['group_id'],mode,candidate_index,predicted)
                runs.append((mask,audit))
        eligible=[(mask,audit) for mask,audit in runs if audit['eligible']]
        best=max(eligible,key=lambda item:item[1]['model_predicted_iou']) if eligible else None
        proposal=dict(group_id=spine['group_id'],region_ids=spine['region_ids'],
                      inference_negative_relation_audit=relation_audit,
                      inference_prompt_keep=prompt_keep.tolist(),
                      points=points.tolist(),labels=labels.tolist(),prompt_box=box.tolist(),
                      full_axis_prompt_box=full_box.tolist(),candidates=[a for _,a in runs],
                      prompt_seconds=time.perf_counter()-prompt_started,selected=best[1] if best else None)
        proposals.append(proposal)
        if best:
            masks[spine['group_id']]=best[0]
            selected=best[1]
            spine.update(book_box=selected['book_box'],spine_polygon=selected['polygon'],
                         sam_mask_contour=selected['mask_contour'],
                         sam_proposal=dict(model_predicted_iou=selected['model_predicted_iou'],
                                           accepted_for_production=False))
    result['audit']['sam_scope']='offline proposals; no production acceptance, inventory count or accuracy claim'
    return result,proposals,masks,dict(image_embedding_seconds=embedding_seconds,
                    mask_prompt_seconds=sum(p['prompt_seconds'] for p in proposals),
                    total_seconds=time.perf_counter()-started)
