"""Expose missing geometric evidence separately from OCR confidence.

These are diagnostic evidence states, not calibrated correctness probabilities.
Never drop transcription or silently relabel hypothesis counts as inventory.
"""
from copy import deepcopy
import cv2
import numpy as np


def annotate_geometry_quality(grouped):
    result=deepcopy(grouped)
    regions=result['regions']
    for spine in result['spines']:
        representative=regions[spine['representative_region_id']]
        evidence=representative.get('upright_geometry_audit')
        if evidence is None:
            continue  # Flat/legacy contracts remain byte-for-byte unchanged.
        polygon=np.asarray(spine['spine_polygon'],np.float32)
        crossed=[]
        for index,region in enumerate(regions):
            other=region.get('spine_group_id')
            if other is None or other==spine['group_id']:
                continue
            title=np.asarray(region['title_box'],np.float32)
            area=cv2.contourArea(cv2.convexHull(title))
            intersection,_=cv2.intersectConvexConvex(polygon,cv2.convexHull(title))
            if area>0 and intersection/area>=.80:
                crossed.append(index)
        boundary=dict(top='supported' if evidence.get('top_cap_supported') else 'unverified',
                      bottom='supported' if evidence.get('bottom_cap_supported') else 'unverified',
                      sides='fitted_at_least_one' if evidence.get('status')=='refined' else 'unverified')
        if evidence.get('side_fit_count')==2:
            boundary['sides']='fitted_both'
        if evidence.get('status')=='clipped_local_seams':
            boundary['bottom']='clipped_outside_frame'
            boundary['sides']='persistent_local_seams'
        reasons=[]
        if crossed:
            reasons.append('contains_other_spine_text')
        if boundary['top']=='unverified':
            reasons.append('top_evidence_missing')
        if boundary['bottom']=='unverified':
            reasons.append('bottom_evidence_missing')
        if boundary['sides'] not in ('fitted_both','persistent_local_seams'):
            reasons.append('side_evidence_incomplete')
        spine['geometry_quality']=dict(
            status='review_required' if reasons else 'supported_visible_hypothesis',
            boundary_evidence=boundary,reasons=reasons,
            intersected_other_region_ids=crossed,
            usable_for_full_spine_crop=not reasons and boundary['bottom']!='clipped_outside_frame',
            semantics='evidence_state_not_accuracy_or_probability')
    result['audit']['geometry_quality_semantics']='Diagnostic evidence only, not calibrated confidence'
    return result
