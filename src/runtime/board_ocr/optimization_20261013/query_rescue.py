"""Bounded, same-image query rescue; a one-edit string selects a crop, never a result."""
import math
from ocr_link.consensus import book_title_key

def one_edit(a,b):
    if abs(len(a)-len(b))>1:return False
    if len(a)==len(b):return sum(x!=y for x,y in zip(a,b))==1
    if len(a)>len(b):a,b=b,a
    i=0
    while i<len(a) and a[i]==b[i]:i+=1
    return a[i:]==b[i+1:]

def candidates(decisions,target,limit=2):
    key=book_title_key(target)
    if len(key)<6 or any(d.get('accepted') and book_title_key(d.get('v4_text',''))==key for d in decisions):return []
    chosen=[]
    from board_ocr.optimization_20261013.native_tiles import bounds,overlap
    for d in sorted(decisions,key=lambda d:d.get('v4_confidence',0),reverse=True):
        if not one_edit(book_title_key(d.get('v4_text','')),key) or d.get('v4_confidence',0)<.65:continue
        b=bounds(d['points'])
        if any(overlap(b,bounds(x['points']))>=.45 for x in chosen):continue
        chosen.append(d)
        if len(chosen)==limit:break
    return chosen

def confirmed(rows,target):
    key=book_title_key(target)
    supported={r['model'] for r in rows if book_title_key(r['text'])==key and math.isfinite(r['confidence']) and r['confidence']>=.95}
    return len(supported)>=2

def rescue(image,decisions,target,primary,secondary,output,detector=None):
    selected=candidates(decisions,target)
    if not selected:return {'attempted':0,'confirmed':0}
    import cv2,numpy as np
    from rapidocr_onnxruntime import RapidOCR
    from board_ocr.optimization_20261013.vertical_text import reflow
    accepted=0
    for d in selected:
        views=[]
        points=np.asarray(d['points'],dtype=np.float32)
        polygons=[points]
        if detector is not None:
            from board_ocr.optimization_20261013.native_roi import refine
            _,_,_,local=refine(image,points,d['v4_text'],d['v4_confidence'],detector,primary,output,10000+d['id'])
            if local.get('local_points'):polygons.append(np.asarray(local['local_points'],dtype=np.float32))
        for polygon in polygons:
            for margin in (0,4):
                center=polygon.mean(axis=0);delta=polygon-center
                lengths=np.maximum(np.linalg.norm(delta,axis=1,keepdims=True),1)
                expanded=polygon+delta/lengths*margin
                expanded[:,0]=np.clip(expanded[:,0],0,image.shape[1]-1);expanded[:,1]=np.clip(expanded[:,1],0,image.shape[0]-1)
                prepared=reflow(image,expanded)
                if prepared is not None:views.append(prepared[0])
                else:views.append(RapidOCR.get_crop_img_list(None,image,[expanded])[0])
        rows=[]
        for model,engine in [('primary',primary),('secondary',secondary)]:
            if engine is None:continue
            result,_=engine(views)
            rows.extend(dict(model=model,view=i,text=text,confidence=float(score)) for i,(text,score) in enumerate(result))
        audit={'method':'native_pixels_query_crop_two_recognizers','original_text':d['v4_text'],'rows':rows,'selected':confirmed(rows,target)}
        d['query_crop_review']=audit
        for i,view in enumerate(views):cv2.imwrite(str(output/f'query_{d["id"]}_{i}.png'),view)
        if audit['selected']:
            support=[r for r in rows if book_title_key(r['text'])==book_title_key(target) and r['confidence']>=.95]
            best=max(support,key=lambda r:r['confidence'])
            d.update(v4_text=best['text'],v4_confidence=min(max(r['confidence'] for r in support if r['model']==model) for model in ('primary','secondary')),accepted=True,reason='same_image_native_query_corroborated')
            from board_ocr.optimization_20261013.native_tiles import bounds,overlap
            for other in decisions:
                if other is not d and other.get('accepted') and other.get('v4_confidence',0)<d['v4_confidence'] and one_edit(book_title_key(other.get('v4_text','')),book_title_key(target)) and overlap(bounds(other['points']),bounds(d['points']))>=.5:
                    other.update(accepted=False,reason='superseded_by_same_region_query_review')
            accepted+=1
    return {'attempted':len(selected),'confirmed':accepted,'max_candidates':2,'title_replaced_from_query':False}
