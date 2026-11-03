"""Blind original-pixel tile detection, including regions missed by coarse OCR."""
import numpy as np
import math


def bounds(points):
    p=np.asarray(points)
    return [float(p[:,0].min()),float(p[:,1].min()),float(p[:,0].max()),float(p[:,1].max())]


def overlap(a,b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return inter/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)


def select_margin(original_text,original_confidence,text,confidence):
    from verification_policy import title_key
    key=title_key(original_text)
    return len(key)>=4 and key==title_key(text) and confidence>=.90 and confidence>=original_confidence+.015


def windows(width,height,roi=None):
    left,top,right,bottom=roi or [0,0,width,height]
    if not (0<=left<right<=width and 0<=top<bottom<=height):raise ValueError('invalid shelf ROI')
    span=min(960,right-left)
    count=max(1,math.ceil((right-left-span)/720)+1)
    starts=[left] if count==1 else [round(left+i*(right-left-span)/(count-1)) for i in range(count)]
    return [[x,top,x+span,bottom] for x in starts]


def detect(image,detector,existing,roi=None,limit=64):
    from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
    previous=detector.get_preprocess
    detector.get_preprocess=lambda max_wh:DetPreProcess(1280,'max',detector.mean,detector.std)
    h,w=image.shape[:2];found=[];audit=[]
    try:
        for rectangle in windows(w,h,roi):
            left,top,right,bottom=rectangle
            boxes,seconds=detector(image[top:bottom,left:right])
            audit.append(dict(roi=rectangle,seconds=float(seconds),boxes=0 if boxes is None else len(boxes)))
            for box in [] if boxes is None else boxes:
                b=bounds(box)
                # Overlap tiles provide a complete alternative to seam-cut words.
                if (left>(roi or [0])[0] and b[0]<8) or (right<(roi or [0,0,w])[2] and b[2]>right-left-8):continue
                points=box+np.array([left,top],dtype=np.float32);b=bounds(points)
                if min(b[2]-b[0],b[3]-b[1])<7 or max(b[2]-b[0],b[3]-b[1])<30:continue
                if any(overlap(b,bounds(p))>=.55 for p in existing):continue
                found.append(points)
    finally:detector.get_preprocess=previous
    # Larger complete boxes win duplicate tile detections; never consult a title.
    found.sort(key=lambda p:(bounds(p)[2]-bounds(p)[0])*(bounds(p)[3]-bounds(p)[1]),reverse=True)
    unique=[]
    for p in found:
        if not any(overlap(bounds(p),bounds(q))>=.55 for q in unique):unique.append(p)
    return unique[:limit],dict(tiles=audit,unique_boxes=len(unique),kept=min(limit,len(unique)),candidate_limit=limit)
