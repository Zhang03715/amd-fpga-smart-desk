"""Reject a weaker conflicting read only when distinct crops agree strongly."""
from collections import defaultdict
from statistics import median
from verification_policy import title_key
from .native_tiles import bounds,overlap


def resolve(decisions,fingerprints):
    voters=[d for d in decisions if d['accepted'] or d.get('reason')=='duplicate_same_text_region']
    rejected=[]
    for d in decisions:
        if not d['accepted'] or d['v4_confidence']>=.95:continue
        key=title_key(d['v4_text'])
        if len(key)<4:continue
        groups=defaultdict(list)
        for other in voters:
            text=title_key(other['v4_text'])
            if (text!=key and min(len(text),len(key))>=.8*max(len(text),len(key))
                    and overlap(bounds(d['points']),bounds(other['points']))>=.65):
                groups[text].append(other)
        supported=[]
        for text,group in groups.items():
            unique={fingerprints[g['id']]:g for g in group}
            if len(unique)>=2 and median(g['v4_confidence'] for g in unique.values())>=.95:
                strongest=max(group,key=lambda g:g['v4_confidence'])
                if strongest['v4_confidence']>=d['v4_confidence']+.015:supported.append((text,group))
        if len(supported)!=1:continue
        text,group=supported[0]
        d.update(accepted=False,reason='weaker_conflicting_transcription',
                 corroborating_ids=[g['id'] for g in group],corroborating_text=text)
        rejected.append(d['id'])
    return dict(rejected_ids=rejected,policy='two_distinct_crops_median_confidence_095_same_region')
