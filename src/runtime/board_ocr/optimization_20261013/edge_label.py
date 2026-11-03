"""Separate small coloured edge labels from a long neutral title line."""
import numpy as np
from verification_policy import title_key


def span(crop):
    import cv2
    h,w=crop.shape[:2]
    if w<4*h:return None
    lab=cv2.cvtColor(crop,cv2.COLOR_BGR2LAB).astype(float)
    bg=np.median(np.concatenate((lab[:2,:,1:],lab[-2:,:,1:]),axis=0).reshape(-1,2),axis=0)
    mask=np.linalg.norm(lab[:,:,1:]-bg,axis=2)>8
    profile=np.convolve(mask.mean(0),np.ones(3)/3,mode='same')>.25
    positions=np.flatnonzero(profile)
    if len(positions)<max(8,w*.025):return None
    groups=np.split(positions,np.flatnonzero(np.diff(positions)>4)+1)
    for group in groups:
        a,b=int(group[0]),int(group[-1])+1
        if b-a<8 or len(group)<len(positions)*.65:continue
        if a<=w*.08 and b<=w*.3:return b+2,w
        if a>=w*.7 and b>=w*.92:return 0,a-2
    return None


def select(original,confidence,text,score,corroborating=None):
    from difflib import SequenceMatcher
    old,new=title_key(original),title_key(text)
    compatible=old.startswith(new) or old.endswith(new)
    corroborated=(confidence<.95 and corroborating is not None and corroborating[1]>=.90
                  and title_key(corroborating[0])==new and SequenceMatcher(None,old,new).ratio()>=.8)
    return (len(new)>=8 and abs(len(old)-len(new))<=2 and (compatible or corroborated)
            and score>=.95 and score>=confidence+.015)


def clipped_points(points,left,right,width):
    p=np.asarray(points,dtype=np.float32);a,b=left/width,right/width
    if np.linalg.norm(p[3]-p[0])>=np.linalg.norm(p[1]-p[0])*1.5:
        return np.array([p[0]+a*(p[3]-p[0]),p[1]+a*(p[2]-p[1]),
                         p[1]+b*(p[2]-p[1]),p[0]+b*(p[3]-p[0])]).tolist()
    return np.array([p[0]+a*(p[1]-p[0]),p[0]+b*(p[1]-p[0]),
                     p[3]+b*(p[2]-p[3]),p[3]+a*(p[2]-p[3])]).tolist()
