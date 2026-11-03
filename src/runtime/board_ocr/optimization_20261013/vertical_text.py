"""Reflow a single upright Chinese column without rotating its glyphs.

Segmentation uses only original pixels. Uncertain/uneven columns are rejected;
no title, dictionary or expected character count is supplied.
"""
import cv2
import numpy as np
from verification_policy import title_key


def reflow(image, points):
    p=np.asarray(points,dtype=np.float32)
    if p.shape!=(4,2) or not np.isfinite(p).all():return None
    ordered=p[np.argsort(p[:,1])]
    top=ordered[:2][np.argsort(ordered[:2,0])]
    bottom=ordered[2:][np.argsort(ordered[2:,0])]
    p=np.array([top[0],top[1],bottom[1],bottom[0]],np.float32)
    w=round((np.linalg.norm(p[1]-p[0])+np.linalg.norm(p[2]-p[3]))/2)
    h=round((np.linalg.norm(p[3]-p[0])+np.linalg.norm(p[2]-p[1]))/2)
    if not (12<=w<=100 and 3*w<=h<=1200):return None
    if min(p[:,0])<0 or min(p[:,1])<0 or max(p[:,0])>=image.shape[1] or max(p[:,1])>=image.shape[0]:return None
    transform=cv2.getPerspectiveTransform(p,np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]],np.float32))
    column=cv2.warpPerspective(image,transform,(w,h))
    gray=cv2.cvtColor(column,cv2.COLOR_BGR2GRAY)
    light=np.median(gray)>110
    mask=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV if light else cv2.THRESH_BINARY,15,4 if light else -4)
    profile=(mask[:,round(w*.15):round(w*.85)]>0).sum(axis=1)
    active=profile>=max(2,w*.08)
    bands=[];start=None
    for y,value in enumerate(np.r_[active,False]):
        if value and start is None:start=y
        if not value and start is not None:
            if bands and start-bands[-1][1]<=1:bands[-1][1]=y
            else:bands.append([start,y])
            start=None
    heights=[b-a for a,b in bands if b-a>=6]
    if len(heights)<4:return None
    typical=float(np.median(heights))
    for _ in range(24):
        choices=[]
        for i,(a,b) in enumerate(bands):
            if b-a>=typical*.65:continue
            for j in (i-1,i+1):
                if 0<=j<len(bands):
                    lo,hi=sorted((i,j));span=bands[hi][1]-bands[lo][0]
                    gap=bands[hi][0]-bands[lo][1]
                    if span<=typical*1.65 and gap<=typical*.4:choices.append((gap,lo,hi))
        if not choices:break
        _,lo,hi=min(choices);bands[lo:hi+1]=[[bands[lo][0],bands[hi][1]]]
    discarded=[]
    while bands and bands[0][1]-bands[0][0]<typical*.5:discarded.append(bands.pop(0))
    while bands and bands[-1][1]-bands[-1][0]<typical*.5:discarded.append(bands.pop())
    if not 4<=len(bands)<=20:return None
    if any(not typical*.55<=b-a<=typical*1.65 for a,b in bands):return None
    if any(b-a<6 for a,b in bands):return None
    cells=[];background=tuple(int(v) for v in np.median(column.reshape(-1,3),axis=0))
    for a,b in bands:
        cell=column[max(0,a-1):min(h,b+1)]
        ch,cw=cell.shape[:2];side=max(ch,cw)
        cell=cv2.copyMakeBorder(cell,(side-ch)//2,side-ch-(side-ch)//2,
            (side-cw)//2,side-cw-(side-cw)//2,cv2.BORDER_CONSTANT,value=background)
        cells.append(cv2.resize(cell,(48,48),interpolation=cv2.INTER_LINEAR))
    return np.concatenate(cells,axis=1),dict(method='upright_glyph_reflow',
        column_size=[w,h],bands=bands,discarded_edge_fragments=discarded,character_cells=len(cells))


def select(original, primary, corroborating, cells):
    text,confidence=primary;again,score=corroborating
    key=title_key(text)
    return (original[1]<.90 and min(confidence,score)>=.90
        and key==title_key(again) and len(key)==cells
        and all('\u4e00'<=c<='\u9fff' for c in key))


def spaced(line,gap=2):
    """A second layout of the same observed glyphs, with a small fixed gap."""
    if line.shape[0]!=48 or line.shape[1]%48:raise ValueError('invalid glyph layout')
    background=np.median(line.reshape(-1,3),axis=0).astype(np.uint8)
    spacer=np.full((48,gap,3),background,np.uint8)
    cells=[line[:,x:x+48] for x in range(0,line.shape[1],48)]
    return np.concatenate([part for cell in cells for part in (cell,spacer)][:-1],axis=1)


def select_strong(original,primary,corroborating,cells):
    """A stronger model may review uncertain accepted text, with tighter gates."""
    confidence=min(primary[1],corroborating[1])
    return (original[1]<.95 and confidence>=.95 and confidence>=original[1]+.015
            and select(('',0.),primary,corroborating,cells))


def review(original,line,cells,recognizer,strong=None):
    attempts=[];seconds=0.
    engines=[]
    if strong is not None and original[1]<.95:engines.append(('medium_glyph',strong,select_strong))
    if original[1]<.90:engines.append(('primary_glyph',recognizer,select))
    for name,engine,choose in engines:
        rows,elapsed=engine([line,spaced(line)])
        elapsed=float(elapsed);seconds+=elapsed
        chosen=choose(original,rows[0],rows[1],cells)
        attempts.append(dict(model=name,text=rows[0][0],confidence=float(rows[0][1]),
            corroborating_text=rows[1][0],corroborating_confidence=float(rows[1][1]),
            selected=bool(chosen),seconds=elapsed))
        if chosen:
            return (rows[0][0],min(float(rows[0][1]),float(rows[1][1]))),dict(
                selected=True,attempts=attempts,seconds=seconds,selected_model=name)
    return original,dict(selected=False,attempts=attempts,seconds=seconds)
