"""Conservative aggregation of OCR regions into physical spine hypotheses.

OCR text is preserved verbatim. Groups are hypotheses, not a proven inventory;
there is no catalogue lookup, colour segmentation or transitive union-find.
"""
from copy import deepcopy
import math
import cv2
import numpy as np


def _polygon(record):
    polygon = record.get('spine_polygon')
    if polygon is None:
        box = record.get('book_box')
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return None
        x1, y1, x2, y2 = box
        polygon = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    try:
        polygon = np.asarray(polygon, np.float32)
        if polygon.shape != (4, 2) or not np.isfinite(polygon).all():
            return None
        polygon = cv2.convexHull(polygon).reshape(-1, 2)
        if len(polygon) != 4 or cv2.contourArea(polygon) < 16:
            return None
        return polygon
    except (ValueError, TypeError, cv2.error):
        return None


def _descriptor(record, index):
    polygon = _polygon(record)
    try:
        title = np.asarray(record.get('title_box'), np.float32)
        if polygon is None or title.shape != (4, 2) or not np.isfinite(title).all():
            return None
        title = cv2.convexHull(title).reshape(-1, 2)
        if len(title) != 4 or cv2.contourArea(title) < 4:
            return None
        center = polygon.mean(axis=0)
        _, vectors = np.linalg.eigh(np.cov((polygon - center).T))
        u = vectors[:, -1]
        if u[np.argmax(np.abs(u))] < 0:
            u = -u
        v = np.array([-u[1], u[0]])
        t, s = polygon @ u, polygon @ v
        length, width = float(np.ptp(t)), float(np.ptp(s))
        clipped_upright = (record.get('visible_region_clipped') is True
                           and record.get('orientation') == 'upright'
                           and record.get('boundary_method') == 'frame_clipped_persistent_colour_seams_experimental'
                           and np.ptp(polygon[:,1]) > np.ptp(polygon[:,0]))
        if (length < width * 2 and not clipped_upright) or width < 3:
            return None
        return dict(index=index, polygon=polygon, title=title, u=u, v=v,
                    length=length, width=width, area=float(cv2.contourArea(polygon)),
                    text_center=title.mean(axis=0), text_length=float(np.ptp(title @ u)))
    except (ValueError, TypeError, cv2.error, np.linalg.LinAlgError):
        return None


def _overlap(first, second):
    try:
        area, _ = cv2.intersectConvexConvex(first, second)
        return float(area) / max(1., min(cv2.contourArea(first), cv2.contourArea(second)))
    except cv2.error:
        return 0.


def _contains(descriptor, title):
    # OCR boxes include antialiasing/margin and existing side fits can be a few
    # pixels off. The tolerance is local spine thickness, capped at 8 pixels.
    tolerance = min(8., max(2., descriptor['width'] * .10))
    return all(cv2.pointPolygonTest(descriptor['polygon'], tuple(map(float, p)), True) >= -tolerance for p in title)


def _pair(first, second):
    cosine = abs(float(np.dot(first['u'], second['u'])))
    if cosine < math.cos(math.radians(10)):
        return False, 'different_physical_axes'
    if _overlap(first['polygon'], second['polygon']) < .60:
        return False, 'insufficient_physical_overlap'
    # Evaluate displacement in the same normal direction, using text anchors,
    # rather than the centers of a truncated author/edition book rectangle.
    distance = abs(float((first['text_center'] - second['text_center']) @ first['v']))
    if distance > min(first['width'], second['width']) * .65:
        return False, 'different_normal_text_bands'
    return True, 'compatible_physical_band'


def _edge_support(image, descriptor):
    """Local seam support ranks existing canonical candidates; not a truth score."""
    if image is None:
        return 0.
    h, w = image.shape[:2]
    polygon = descriptor['polygon']
    scores = []
    for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
        direction = b - a
        length = np.linalg.norm(direction)
        if length < descriptor['length'] * .35:
            continue
        if abs(float(np.dot(direction / length, descriptor['u']))) < .85:
            continue
        points = a[None, :] + np.linspace(.08, .92, 35)[:, None] * direction[None, :]
        strengths = []
        for offset in (-3., 0., 3.):
            centers = points + offset * descriptor['v']
            minus = np.rint(centers - descriptor['v'] * 3).astype(int)
            plus = np.rint(centers + descriptor['v'] * 3).astype(int)
            valid = ((minus[:, 0] >= 0) & (minus[:, 0] < w) & (plus[:, 0] >= 0) & (plus[:, 0] < w)
                     & (minus[:, 1] >= 0) & (minus[:, 1] < h) & (plus[:, 1] >= 0) & (plus[:, 1] < h))
            if not valid.any():
                continue
            delta = np.linalg.norm(image[minus[valid, 1], minus[valid, 0]].astype(float)
                                   - image[plus[valid, 1], plus[valid, 0]].astype(float), axis=1)
            strengths.append(float(np.mean(delta > 12)))
        if strengths:
            scores.append(max(strengths))
    return min(scores) if len(scores) >= 2 else 0.


def _canonical(members, image):
    candidates = [candidate for candidate in members if all(_contains(candidate, member['title']) for member in members)]
    if not candidates:
        return None
    # Prefer existing full-length polygons. Do not union author/edition boxes
    # into a larger envelope; seam evidence only breaks comparable candidates.
    longest = max(candidate['length'] for candidate in candidates)
    candidates = [candidate for candidate in candidates if candidate['length'] >= longest * .95]
    return max(candidates, key=lambda candidate: (
        _edge_support(image, candidate), candidate['text_length'], candidate['length'], -candidate['index']))


def _crosswise_label(descriptor, descriptors):
    """Reject a short text's extrapolated strip across several taller spines.

    This uses local opposing geometry, not a global vertical-only assumption.
    A real horizontal book with a long title can still anchor its own group.
    """
    if descriptor['length'] < 4 * max(1., descriptor['text_length']):
        return False
    crossing = []
    for other in descriptors:
        if other is None or other is descriptor:
            continue
        if (abs(float(np.dot(descriptor['u'], other['u']))) < .35
                and other['text_length'] > 2 * descriptor['text_length']
                and other['length'] > 2 * descriptor['width']
                and _overlap(descriptor['polygon'], other['polygon']) > .05):
            crossing.append(other)
    return len(crossing) >= 2


def group_spine_regions(image, records, *, crosswise_cleanup=False):
    """Return spines/regions/audit without mutating or dropping original records.

    Region IDs are zero-based input positions. Ambiguous bridge/no-geometry text
    has spine_group_id=None, rather than inventing another physical book.
    Canonical polygons are selected existing evidence, never a bounding union.
    """
    if not isinstance(records, list):
        raise ValueError('records must be a list')
    if image is not None and (not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3):
        raise ValueError('image must be a three-channel array or None')
    regions = deepcopy(records)
    descriptors = [_descriptor(record, i) if isinstance(record, dict) else None for i, record in enumerate(records)]
    if any(not isinstance(record, dict) for record in records):
        raise ValueError('every OCR record must be an object')
    for region in regions:
        region['spine_group_id'] = None
    groups, unresolved = [], []
    reasons = {}
    deferred = set()
    for descriptor in descriptors if crosswise_cleanup else []:
        if descriptor is not None and _crosswise_label(descriptor, descriptors):
            deferred.add(descriptor['index'])
            reasons[descriptor['index']] = 'crosswise_short_text_extrapolation'
    # Narrow physical bands first prevent a broad erroneous two-book box from
    # becoming the anchor which absorbs both legitimate neighbouring spines.
    ordered = sorted((d for d in descriptors if d is not None and d['index'] not in deferred), key=lambda d: (d['width'], -d['length'], d['index']))
    for descriptor in ordered:
        touched = [group for group in groups if any(_overlap(descriptor['polygon'], member['polygon']) >= .60 for member in group)]
        if len(touched) > 1:
            unresolved.append(descriptor)
            reasons[descriptor['index']] = 'incompatible_cross_spine_bridge'
            continue
        compatible = []
        for index, group in enumerate(groups):
            if all(_pair(descriptor, member)[0] for member in group):
                candidate = _canonical(group + [descriptor], image)
                if candidate is not None:
                    compatible.append(index)
        if len(compatible) == 1:
            groups[compatible[0]].append(descriptor)
        elif len(compatible) > 1:
            unresolved.append(descriptor)
            reasons[descriptor['index']] = 'ambiguous_cross_spine_bridge'
        else:
            # A member which overlaps different normal bands cannot create a
            # third inventory hypothesis between two already anchored books.
            if len(touched) > 1:
                unresolved.append(descriptor)
                reasons[descriptor['index']] = 'incompatible_cross_spine_bridge'
            else:
                groups.append([descriptor])
    # A short same-axis publisher fragment can straddle the side of the full
    # book. Attach by unique text containment only, keeping the full polygon.
    removed = set()
    for g, group in enumerate(groups) if crosswise_cleanup else []:
        if len(group) != 1:
            continue
        fragment = group[0]
        parents = []
        for p, parent in enumerate(groups):
            if p == g or p in removed:
                continue
            canonical = _canonical([m for m in parent if not m.get('auxiliary')], image)
            if (canonical is not None and fragment['length'] < canonical['length'] * .65
                    and abs(float(np.dot(fragment['u'], canonical['u']))) > .98
                    and _contains(canonical, fragment['title'])):
                parents.append(p)
        if len(parents) == 1:
            groups[parents[0]].append(dict(index=fragment['index'], title=fragment['title'], auxiliary=True))
            removed.add(g)
            reasons[fragment['index']] = 'short_fragment_attached_by_unique_containment'
    groups = [group for g, group in enumerate(groups) if g not in removed]
    # Crosswise tiny publisher/author OCR can have weak/inaccurate book boxes.
    # Attach only if its complete OCR quad lies in exactly one existing spine.
    for index, descriptor in enumerate(descriptors):
        if descriptor is not None and index not in deferred:
            continue
        try:
            title = np.asarray(records[index].get('title_box'), np.float32)
            matches = [g for g in range(len(groups)) if title.shape == (4, 2)
                       and np.isfinite(title).all() and _contains(_canonical([m for m in groups[g] if not m.get('auxiliary')], image), title)]
        except (ValueError, TypeError):
            matches = []
        if len(matches) == 1:
            # This member does not influence axis, envelope or canonical choice.
            reasons[index] = 'crosswise_text_attached_by_unique_containment'
            groups[matches[0]].append(dict(index=index, title=title, auxiliary=True))
        else:
            reasons[index] = 'unresolved_text_geometry'
    groups.sort(key=lambda group: min(member['index'] for member in group))
    spines = []
    for number, group in enumerate(groups, 1):
        physical = [member for member in group if not member.get('auxiliary')]
        canonical = _canonical(physical, image)
        if canonical is None:
            for member in group:reasons[member['index']]='no_supported_canonical_polygon'
            continue
        group_id = 'spine_' + str(number)
        ids = sorted(member['index'] for member in group)
        polygon = canonical['polygon'].round().astype(int).tolist()
        box = [min(p[0] for p in polygon), min(p[1] for p in polygon), max(p[0] for p in polygon), max(p[1] for p in polygon)]
        center = canonical['polygon'].mean(axis=0)
        h, w = image.shape[:2] if image is not None else (None, None)
        spines.append(dict(group_id=group_id, region_ids=ids, text_region_ids=ids,
                           book_box=box, spine_polygon=polygon, canonical_polygon=polygon,
                           representative_region_id=canonical['index'],
                           normalized_center=[round(float(center[0] / w), 4), round(float(center[1] / h), 4)] if w and h else None,
                           location_center=center.tolist(), member_count=len(ids),
                           semantics='physical_spine_hypothesis_not_confirmed_book'))
        for index in ids:
            regions[index]['spine_group_id'] = group_id
    for index, region in enumerate(regions):
        region['text_region_id'] = index
        region.setdefault('spine_group_id', None)
    return dict(spines=spines, regions=regions, audit=dict(
        method=('physical_band_complete_link_existing_polygon_v2_experimental' if crosswise_cleanup
                else 'physical_band_complete_link_existing_polygon_v1'),
        text_regions=len(records), book_hypotheses=len(spines),
        count_semantics='book_hypotheses_not_proven_inventory',
        unresolved_region_ids=[i for i, region in enumerate(regions) if region['spine_group_id'] is None],
        region_notes={str(i): reason for i, reason in reasons.items()},
        canonical_method='select_supported_existing_member_no_union',
        preserves_original_transcriptions=True, uses_text_semantics=False,
        image_seams_role='rank_existing_candidate_polygons_not_colour_segmentation'))
