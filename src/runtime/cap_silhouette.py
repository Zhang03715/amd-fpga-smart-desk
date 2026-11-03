"""Independent upright-cap experiment using seeded local GrabCut silhouettes.

No references, case IDs, catalogue, or quiet-band endpoint rules are consulted.
This estimates the visible object's silhouette, which can include a back cover;
it is not proof of the printed front spine plane. Defaults elsewhere are intact.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import cv2
import numpy as np


def refine_silhouette_caps(image, points, existing_box, existing_polygon=None, *, debug=None, apply_candidates=False):
    audit = dict(method='local_seeded_grabcut_silhouette_v1', accepted=False,
                 confidence_semantics='heuristic_not_probability', confidence=0.,
                 object_plane='visible_silhouette_not_guaranteed_printed_spine')
    def reject(reason):
        audit['reason'] = reason
        return existing_box, existing_polygon, audit
    try:
        if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            return reject('invalid_image')
        h, w = image.shape[:2]
        pts = np.asarray(points, float)
        box = np.asarray(existing_box, float)
        if pts.shape != (4, 2) or box.shape != (4,) or not np.isfinite(pts).all() or not np.isfinite(box).all():
            return reject('invalid_geometry')
        text_span = np.ptp(pts, axis=0)
        if text_span[1] < text_span[0] * 2 or text_span[1] < 30:
            return reject('not_upright_anchor')
        poly = np.asarray(existing_polygon if existing_polygon is not None else
                          [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]], float)
        if poly.shape != (4, 2) or not np.isfinite(poly).all():
            return reject('invalid_geometry')
        order = np.argsort(poly[:, 1])
        top = poly[order[:2]][np.argsort(poly[order[:2], 0])]
        bottom = poly[order[2:]][np.argsort(poly[order[2:], 0])]
        if bottom[:, 1].min() <= top[:, 1].max():
            return reject('invalid_upright_polygon')
        def project(first, last, ys):
            return first[0] + (last[0]-first[0]) * (ys-first[1]) / (last[1]-first[1])
        ys = np.arange(h, dtype=float)
        lx, rx = project(top[0], bottom[0], ys), project(top[1], bottom[1], ys)
        widths = rx-lx
        if np.min(widths) < 5 or np.median(widths) > w*.70:
            return reject('invalid_side_corridor')
        x0 = max(0, int(np.floor(np.min(lx-widths*.35))))
        x1 = min(w, int(np.ceil(np.max(rx+widths*.35)))+1)
        if x1-x0 < 12:
            return reject('insufficient_local_context')
        crop = image[:, x0:x1]
        scale = min(1., 600/h, 300/(x1-x0))
        local = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        hh, ww = local.shape[:2]
        local_y = np.arange(hh)/scale
        left = (project(top[0], bottom[0], local_y)-x0)*scale
        right = (project(top[1], bottom[1], local_y)-x0)*scale
        normal_width = right-left
        columns = np.arange(ww)[None,:]
        corridor = (columns>=left[:,None])&(columns<=right[:,None])
        mask = np.full((hh, ww), cv2.GC_BGD, np.uint8)
        mask[corridor] = cv2.GC_PR_FGD
        # A narrow uncertain halo permits a few pixels of imperfect side fits,
        # but the surrounding neighbours remain definite background seeds.
        halo=(columns>=left[:,None]-normal_width[:,None]*.12)&(columns<=right[:,None]+normal_width[:,None]*.12)
        mask[halo&~corridor] = cv2.GC_PR_BGD
        seed_points=(pts-np.array([x0,0]))*scale
        center=seed_points.mean(axis=0)
        seed_points=center+(seed_points-center)*.80
        seed=np.zeros(mask.shape,np.uint8)
        cv2.fillConvexPoly(seed,np.rint(seed_points).astype(np.int32),1)
        seed &= corridor.astype(np.uint8)
        if seed.sum()<20 or np.sum(mask==cv2.GC_BGD)<100:
            return reject('insufficient_fg_bg_seeds')
        mask[seed.astype(bool)] = cv2.GC_FGD
        cv2.grabCut(local,mask,None,np.zeros((1,65),float),np.zeros((1,65),float),3,cv2.GC_INIT_WITH_MASK)
        foreground=(mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD)
        # Reconnect short printed-label gaps before extracting the silhouette;
        # all reconnection remains inside this one fitted side corridor/halo.
        close_h=max(3,int(np.median(normal_width)*.45)|1)
        close_w=max(3,int(np.median(normal_width)*.10)|1)
        foreground=cv2.morphologyEx(foreground.astype(np.uint8),cv2.MORPH_CLOSE,
                                   np.ones((close_h,close_w),np.uint8)).astype(bool)&halo
        count, labels, stats, _=cv2.connectedComponentsWithStats(foreground.astype(np.uint8),8)
        candidates=[]
        for label in range(1,count):
            overlap=int(np.sum((labels==label)&seed.astype(bool)))
            if overlap:
                candidates.append((overlap,int(stats[label,cv2.CC_STAT_AREA]),label))
        if not candidates:
            return reject('no_seed_connected_silhouette')
        candidates.sort(reverse=True)
        best=candidates[0][2]
        body=(labels==best).astype(np.uint8)
        anchor_coverage=float(np.sum(body&seed)/seed.sum())
        if anchor_coverage<.85:
            audit['seed_connected_coverage']=anchor_coverage
            return reject('fragmented_anchor_silhouette')
        # Fill enclosed holes (e.g. white call-number labels) instead of ending
        # at their printed colour transition. Other detached components stay out.
        contours,_=cv2.findContours(body,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        filled=np.zeros_like(body)
        cv2.drawContours(filled,contours,-1,1,cv2.FILLED)
        occupancy=np.sum(filled&corridor,axis=1)/np.maximum(1,np.sum(corridor,axis=1))
        active=occupancy>=.85
        # Only short segmentation gaps can be bridged; large uncertain holes
        # cause a rejection, not an invented full book extent.
        good=np.flatnonzero(active)
        max_gap=max(2,int(np.median(normal_width)*.30))
        for first,last in zip(good[:-1],good[1:]):
            if last-first-1<=max_gap: active[first:last+1]=True
        center_row=int(np.clip(np.mean(seed_points[:,1]),0,hh-1))
        if not active[center_row]:
            return reject('no_broad_silhouette_at_anchor')
        start=end=center_row
        while start>0 and active[start-1]: start-=1
        while end+1<hh and active[end+1]: end+=1
        # A rounded bottom cap tapers below the broad body. Recover only its
        # connected contour tail over a small thickness-scaled distance; unlike
        # the top, this cannot absorb a tall rear-cover tab above the front face.
        tail_limit=min(hh-1,end+max(2,int(np.median(normal_width)*.15)))
        for row in range(end+1,tail_limit+1):
            if occupancy[row]<.10:break
            end=row
        new_top,new_bottom=int(round(start/scale)),min(h-1,int(round(end/scale)))
        if new_top>pts[:,1].min()+2 or new_bottom<pts[:,1].max()-2:
            return reject('silhouette_cuts_ocr_anchor')
        proposed_top,proposed_bottom=new_top,new_bottom
        cap_status={}
        # A 2-D silhouette can include a rear cover/nearby object. It supplies
        # no plane evidence for enlarging a previously fitted front-spine cap.
        # A cap hugging the OCR seed can also be a segmentation colour break.
        margin=max(4.,text_span[0]*.5)
        if new_top<int(box[1])-3:
            new_top=int(box[1]);cap_status['top']='outward_plane_ambiguous_keep_existing'
        elif pts[:,1].min()-new_top<margin:
            new_top=int(box[1]);cap_status['top']='too_close_to_ocr_seed_keep_existing'
        else:cap_status['top']='silhouette_candidate'
        if new_bottom>int(box[3])+3:
            new_bottom=int(box[3]);cap_status['bottom']='outward_plane_ambiguous_keep_existing'
        elif new_bottom-pts[:,1].max()<margin:
            new_bottom=int(box[3]);cap_status['bottom']='too_close_to_ocr_seed_keep_existing'
        else:cap_status['bottom']='silhouette_candidate'
        # An external side contour continuing beyond an apparent bottom is
        # independent counter-evidence: e.g. a colour-switched catalogue label.
        if new_bottom<int(box[3])-5:
            lab=cv2.cvtColor(crop,cv2.COLOR_BGR2LAB).astype(float)
            normal=float(np.median(widths))
            rows=np.linspace(new_bottom+8,min(int(box[3])-2,new_bottom+normal*.8),18)
            continued=[]
            for first,last in ((top[0],bottom[0]),(top[1],bottom[1])):
                strong=[]
                for y in rows:
                    x=float(project(first,last,y))-x0
                    deltas=[]
                    for offset in np.linspace(-min(5,normal*.06),min(5,normal*.06),5):
                        xa,xb=int(round(x+offset-3)),int(round(x+offset+3));yy=int(round(y))
                        if 0<=yy<h and 0<=xa<x1-x0 and 0<=xb<x1-x0:
                            deltas.append(float(np.linalg.norm(lab[yy,xa]-lab[yy,xb])))
                    strong.append(max(deltas,default=0.)>10.)
                continued.append(float(np.mean(strong)))
            audit['side_continuation_below_candidate']=continued
            if min(continued)>.5 or max(continued)>.80:
                new_bottom=int(box[3]);cap_status['bottom']='continuing_side_contour_keep_existing'
        cap_poly=[]
        for first,last,y in ((top[0],bottom[0],new_top),(top[1],bottom[1],new_top),
                             (top[1],bottom[1],new_bottom),(top[0],bottom[0],new_bottom)):
            cap_poly.append([int(round(np.clip(project(first,last,y),0,w-1))),int(y)])
        cap_box=[min(p[0] for p in cap_poly),new_top,max(p[0] for p in cap_poly),new_bottom]
        if debug is not None:
            debug.update(crop=local.copy(), raw_mask=foreground.astype(np.uint8)*255,
                         filled_mask=filled*255, x_origin=x0, scale=float(scale))
        confidence=min(anchor_coverage,float(np.mean(occupancy[start:end+1])))
        audit.update(candidate_box=cap_box,candidate_polygon=cap_poly,
                     raw_silhouette_endpoints=[proposed_top,proposed_bottom],cap_status=cap_status,
                     seed_connected_coverage=round(anchor_coverage,4),
                     broad_silhouette_occupancy=round(float(np.mean(occupancy[start:end+1])),4),
                     confidence=round(confidence,4),top_clipped=start==0,bottom_clipped=end==hh-1,
                     foreground_components=count-1)
        if confidence<.78:
            return reject('weak_silhouette_coverage')
        # A nontrivial cap move needs visible foreground rows and background
        # separation; crop-frame contact is explicitly uncertain.
        if start==0 and new_top!=int(box[1]):
            return reject('top_silhouette_clipped')
        if end==hh-1 and new_bottom!=int(box[3]):
            return reject('bottom_silhouette_clipped')
        if new_top==int(box[1]) and new_bottom==int(box[3]):
            return reject('silhouette_unresolved_keep_existing')
        audit.update(silhouette_candidate_supported=True,review_required=True,
                     warning='visible silhouette can include rear/side cover or occluder')
        if not apply_candidates:
            return reject('printed_front_plane_requires_review')
        audit.update(accepted=True,reason='seeded_external_silhouette',
                     warning='visible silhouette can include rear/side cover or occluder')
        return cap_box,cap_poly,audit
    except (ValueError,TypeError,IndexError,cv2.error,np.linalg.LinAlgError):
        return reject('segmentation_or_geometry_failed')


def refine_silhouette_records(image,records,*,apply_candidates=False):
    result=deepcopy(records)
    for record in result:
        box,polygon,audit=refine_silhouette_caps(image,record['title_box'],record['book_box'],record.get('spine_polygon'),apply_candidates=apply_candidates)
        record['book_box'],record['spine_polygon']=box,polygon
        record['cap_silhouette_audit']=audit
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--records',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--apply-candidates',action='store_true',help='Offline experiment only: apply unverified silhouette proposals')
    args=parser.parse_args()
    image=cv2.imread(str(args.image))
    if image is None: parser.error('cannot read image')
    records=json.loads(args.records.read_text(encoding='utf8'))
    args.output.mkdir(parents=True,exist_ok=False)
    refined=deepcopy(records)
    before,after=image.copy(),image.copy()
    for i,(old,new) in enumerate(zip(records,refined)):
        debug={}
        box,poly,audit=refine_silhouette_caps(image,old['title_box'],old['book_box'],old.get('spine_polygon'),debug=debug,apply_candidates=args.apply_candidates)
        new.update(book_box=box,spine_polygon=poly,cap_silhouette_audit=audit)
        for canvas,row,color in ((before,old,(255,140,0)),(after,new,(0,220,0) if audit['accepted'] else (0,160,255))):
            p=row.get('spine_polygon')
            if p is None:
                x1,y1,x2,y2=row['book_box'];p=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
            cv2.polylines(canvas,[np.asarray(p,np.int32)],True,color,2)
            cv2.putText(canvas,str(i),(int(row['book_box'][0]),max(15,int(row['book_box'][1]))),cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
        if debug:
            cv2.imwrite(str(args.output/f'{i:02d}-crop.jpg'),debug['crop'])
            cv2.imwrite(str(args.output/f'{i:02d}-mask.png'),debug['filled_mask'])
    (args.output/'result.json').write_text(json.dumps(dict(original=records,refined=refined,
                            scope='static saved OCR geometry; no OCR inference or reference coordinates used'),
                            ensure_ascii=False,indent=2),encoding='utf8')
    cv2.imwrite(str(args.output/'before.jpg'),before)
    cv2.imwrite(str(args.output/'after.jpg'),after)
    cv2.imwrite(str(args.output/'comparison.jpg'),np.concatenate((before,after),axis=1))
    print(json.dumps({'regions':len(records),'accepted':sum(r['cap_silhouette_audit']['accepted'] for r in refined)}))


if __name__=='__main__': main()
