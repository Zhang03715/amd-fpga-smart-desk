"""Experimental cap refinement requiring silhouette and image-edge evidence.

Never reads annotations. A colour boundary alone is not a physical endpoint.
The caller must retain neighbour/title validation and review-only status.
"""
import cv2
import numpy as np


def refine_supported_caps(image,mask,quad,title_boxes=()):
    quad=np.asarray(quad,np.float32)
    audit={'method':'silhouette_and_image_edge_caps','applied':False,'ends':[]}
    sides=np.linalg.norm(np.roll(quad,-1,axis=0)-quad,axis=1)
    if sides[0]+sides[2]>sides[1]+sides[3]:
        quad=np.roll(quad,-1,axis=0)
        sides=np.roll(sides,-1)
    direction=(quad[2]+quad[3]-quad[0]-quad[1])/2
    if abs(direction[1])<abs(direction[0])*4:
        audit['reason']='not_upright_front_cap'
        return quad,audit
    if direction[1]<0:
        quad=quad[[3,2,1,0]]
    if quad[:,0].min()<=1 or quad[:,0].max()>=image.shape[1]-2:
        # A clipped side cannot establish a reliable full-width body/cap.
        audit['reason']='short_axis_side_clipped_by_frame'
        return quad,audit
    width=int(round((sides[0]+sides[2])/2))
    height=int(round((sides[1]+sides[3])/2))
    if width<12 or height<max(60,width*2):
        audit['reason']='insufficient_elongated_body'
        return quad,audit
    # Bound working buffers independently of input resolution.
    scale=min(1.,128/width,1000/height)
    width=max(12,int(round(width*scale)))
    height=max(60,int(round(height*scale)))
    target=np.asarray([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],np.float32)
    transform=cv2.getPerspectiveTransform(quad,target)
    inverse=cv2.getPerspectiveTransform(target,quad)
    warped=cv2.warpPerspective(image,transform,(width,height))
    silhouette=cv2.warpPerspective(np.asarray(mask,np.uint8),transform,(width,height),flags=cv2.INTER_NEAREST)
    lab=cv2.cvtColor(cv2.GaussianBlur(warped,(3,3),0),cv2.COLOR_BGR2LAB).astype(float)
    start,end=0,height-1
    start_line=np.asarray([0.,0.])
    end_line=np.asarray([height-1.,height-1.])
    # Rear-cover protrusions are an upright TOP hypothesis. Bottom labels,
    # curved book feet and flat stacks do not provide the same evidence.
    for reverse in (False,):
        colors=lab[::-1] if reverse else lab
        body=silhouette[::-1] if reverse else silhouette
        # Ink/label holes must not imitate a narrow cap. Use the span between
        # the outer silhouette pixels rather than the fraction of filled ink.
        occupied=body>0
        any_pixels=occupied.any(axis=1)
        left=occupied.argmax(axis=1)
        right=width-1-occupied[:,::-1].argmax(axis=1)
        occupancy=np.where(any_pixels,(right-left+1)/width,0.)
        # Demand a preceding narrow protrusion and a sustained full-width body.
        run=max(3,int(round(height*.008)))
        span=min(int(height*.15),height-run-3)
        candidates=[]
        width_supported=0
        strongest_edge_support=0.
        margin=max(1,int(width*.10))
        for y in range(run+2,span):
            lookback=max(run,int(height*.08))
            if np.min(occupancy[y:y+run])<.90 or np.median(occupancy[max(0,y-lookback):y])>.85:
                continue
            width_supported+=1
            columns=np.arange(margin,width-margin)
            # A perspective cap need not be horizontal in the body rectangle.
            # Require a coherent oblique edge, not independent per-pixel peaks.
            for slope in (-.3,-.2,-.1,0.,.1,.2,.3):
                edge_y=np.rint(y+slope*(columns-(width-1)/2)).astype(int)
                if edge_y.min()<3 or edge_y.max()+3>=height:
                    continue
                before=np.median(np.stack([colors[edge_y-d,columns] for d in (1,2,3)]),axis=0)
                after=np.median(np.stack([colors[edge_y+d,columns] for d in (0,1,2)]),axis=0)
                delta=np.linalg.norm(after-before,axis=1)
                support=float(np.mean(delta>=10.))
                strongest_edge_support=max(strongest_edge_support,support)
                if support>.50:
                    candidates.append((float(np.median(delta)),y,support,slope))
        entry={'end':'last' if reverse else 'first','candidates':len(candidates),
               'width_supported_rows':width_supported,'strongest_edge_support':strongest_edge_support}
        if candidates:
            strength,y,support,slope=max(candidates)
            line=y+slope*(np.asarray([0.,width-1.])-(width-1)/2)
            # Refinement can only trim the original quad.
            line=np.clip(line,0,height-1)
            entry.update(trim_pixels=y,edge_strength=strength,edge_support=support,slope=slope)
            if reverse:
                end=height-1-y
                end_line=height-1-line
            else:
                start=y
                start_line=line
        audit['ends'].append(entry)
    if start==0 and end==height-1:
        audit['reason']='no_joint_silhouette_and_edge_support'
        return quad,audit
    rect=np.asarray([[[0,start_line[0]],[width-1,start_line[1]],
                      [width-1,end_line[1]],[0,end_line[0]]]],np.float32)
    proposed=cv2.perspectiveTransform(rect,inverse)[0]
    for title in title_boxes:
        hull=cv2.convexHull(np.asarray(title,np.float32).reshape(-1,1,2))
        area=cv2.contourArea(hull)
        overlap,_=cv2.intersectConvexConvex(proposed,hull)
        if area<=0 or overlap/area<.90:
            audit['reason']='would_trim_group_text'
            return quad,audit
    audit.update(applied=True,reason='joint_support_not_physical_acceptance',start=start,end=end)
    return proposed,audit
