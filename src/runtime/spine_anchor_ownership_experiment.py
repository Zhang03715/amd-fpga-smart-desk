"""Offline ownership proposal: an existing anchor must support every member.

No boundary union, annotation access, inference integration or relaxed pair gate.
"""
from copy import deepcopy
import numpy as np
from spine_groups import _descriptor, _contains, _pair


def propose_anchor_ownership(result):
    out = deepcopy(result)
    regions = out['regions']
    descriptors = [_descriptor(r, i) for i, r in enumerate(regions)]
    groups = out['spines']
    proposals = []
    for anchor in descriptors:
        if anchor is None:
            continue
        supported = []
        for group in groups:
            members = [descriptors[i] for i in group['region_ids']]
            if all(m is not None and anchor['text_length'] >= m['text_length']
                   and _pair(anchor, m)[0] and _contains(anchor, m['title']) for m in members):
                supported.append(group)
        ids = sorted({anchor['index']} | {i for g in supported for i in g['region_ids']})
        touched = [g for g in groups if any(_contains(anchor, descriptors[i]['title'])
                   for i in g['region_ids'] if descriptors[i] is not None)]
        # A partially covered group is evidence of ambiguity, not permission to split it.
        if (len(supported) >= 2 and len(touched) == len(supported)
                and all(regions[i]['spine_group_id'] is None or
                        any(regions[i]['spine_group_id'] == g['group_id'] for g in supported)
                        for i in ids)):
            proposals.append(dict(anchor=anchor['index'], regions=ids,
                                  groups=[g['group_id'] for g in supported]))
    # Competing proposals sharing any region remain unresolved, without greedy order effects.
    accepted = [p for p in proposals if not any(
        p is not q and set(p['regions']) & set(q['regions']) for q in proposals)]
    for proposal in accepted:
        old = [g for g in groups if g['group_id'] in proposal['groups']]
        new = deepcopy(old[0])
        anchor = descriptors[proposal['anchor']]
        polygon = anchor['polygon'].round().astype(int)
        center = polygon.mean(axis=0)
        new.update(region_ids=proposal['regions'], text_region_ids=proposal['regions'],
                   representative_region_id=proposal['anchor'], member_count=len(proposal['regions']),
                   spine_polygon=polygon.tolist(), canonical_polygon=polygon.tolist(),
                   book_box=[int(x) for x in [polygon[:,0].min(), polygon[:,1].min(),
                                             polygon[:,0].max(), polygon[:,1].max()]],
                   location_center=center.tolist())
        # Preserve image normalization using the old valid coordinate scale.
        old_center = np.asarray(old[0]['location_center'])
        old_normalized = np.asarray(old[0]['normalized_center'])
        new['normalized_center'] = (center * old_normalized / old_center).round(4).tolist()
        groups[:] = [g for g in groups if g['group_id'] not in proposal['groups']] + [new]
        for i in proposal['regions']:
            regions[i]['spine_group_id'] = new['group_id']
            out['audit'].setdefault('region_notes', {})[str(i)] = 'existing_anchor_ownership_experimental'
    groups.sort(key=lambda g: min(g['region_ids']))
    out['audit'].update(method='existing_anchor_star_ownership_offline_experiment',
                        book_hypotheses=len(groups),
                        unresolved_region_ids=[i for i,r in enumerate(regions) if r['spine_group_id'] is None],
                        anchor_proposals=proposals, accepted_anchor_proposals=accepted)
    return out
