"""Blind orientation rescue; corroborated fallback cannot consult a target."""
import numpy as np
from verification_policy import title_key


def restore_points(points,left,top,height):
    p=np.asarray(points,dtype=np.float32)
    return np.column_stack((p[:,1]+left,height-1-p[:,0]+top)).astype(np.float32)


def choose(primary,secondary,padded):
    text,confidence=primary
    other,score=secondary;again,again_score=padded
    conflict=(confidence>=.90 and score>=.90 and title_key(text)!=title_key(other))
    selected=(confidence<.90 and min(score,again_score)>=.90
              and len(title_key(other))>=4 and title_key(other)==title_key(again))
    return ((other,min(score,again_score)) if selected else primary),dict(
        secondary_text=other,secondary_confidence=float(score),padded_text=again,
        padded_confidence=float(again_score),selected=selected,conflict=conflict)


def needs_padding(primary,secondary):
    # These are necessary conditions of choose's fallback rule. If any fails,
    # no possible padded result could change the selected transcription.
    return primary[1]<.90 and secondary[1]>=.90 and len(title_key(secondary[0]))>=4
