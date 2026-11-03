"""Target-independent title re-detection on original pixels, with audited choice."""
import numpy as np
from verification_policy import title_key


def bounds(points):
    a=np.asarray(points,dtype=np.float32)
    return [float(a[:,0].min()),float(a[:,1].min()),float(a[:,0].max()),float(a[:,1].max())]


def overlap(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return area/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def choose(original_text,original_confidence,text,confidence):
    old,new=title_key(original_text),title_key(text)
    # Do not substitute an adjacent publisher or a fragment of the original line.
    compatible=bool(new) and abs(len(new)-len(old))<=2
    selected=compatible and confidence>=.90 and confidence>=original_confidence+.015
    conflict=compatible and old!=new and original_confidence>=.90 and confidence>=.90
    return selected,conflict


def refine(image,points,original_text,original_confidence,detector,recognizer,output,index):
    import cv2
    from rapidocr_onnxruntime import RapidOCR
    b=bounds(points);w,h=b[2]-b[0],b[3]-b[1]
    mx=max(12,round(w*(.5 if h>w else .12)))
    my=max(12,round(h*(.12 if h>w else .5)))
    left,top=max(0,int(b[0])-mx),max(0,int(b[1])-my)
    right,bottom=min(image.shape[1],int(b[2])+mx),min(image.shape[0],int(b[3])+my)
    audit=dict(roi=[left,top,right,bottom],original_points=points,original_text=original_text,
               original_confidence=float(original_confidence),selected=False,conflict=False)
    if min(right-left,bottom-top)<16 or max(right-left,bottom-top)>1200:
        return original_text,original_confidence,points,dict(audit,reason='roi_size_limit')
    region=image[top:bottom,left:right]
    boxes,seconds=detector(region)
    candidates=[] if boxes is None else [box+np.array([left,top],dtype=np.float32) for box in boxes]
    candidates=[box for box in candidates if overlap(b,bounds(box))>=.45]
    if not candidates:return original_text,original_confidence,points,dict(audit,reason='no_corresponding_local_box')
    best=max(candidates,key=lambda box:overlap(b,bounds(box)))
    crop=RapidOCR.get_crop_img_list(None,image,[best])[0]
    name=f'native_{index:03d}.png'
    if not cv2.imwrite(str(output/name),crop):raise RuntimeError('native crop write failed')
    variants=[crop,cv2.rotate(crop,cv2.ROTATE_180)]
    rows,recognition_seconds=recognizer(variants)
    text,confidence=max(rows,key=lambda row:float(row[1]));confidence=float(confidence)
    selected,conflict=choose(original_text,original_confidence,text,confidence)
    audit.update(crop_file=name,local_points=best.tolist(),iou=overlap(b,bounds(best)),
                 text=text,confidence=confidence,selected=selected,conflict=conflict,
                 detection_seconds=float(seconds),recognition_seconds=float(recognition_seconds),
                 variants=[dict(text=t,confidence=float(c)) for t,c in rows])
    return (text,confidence,best.tolist(),audit) if selected else (original_text,original_confidence,points,audit)
