"""Opt-in geometric experiment: OCR direction seeds image seam/end searches.

An OCR region is a geometric anchor, not proof of a title or a unique book.
Both supported side seams and visible image ends are required. Weak evidence
returns the exact existing box/polygon, never a text-length-derived substitute.
"""
import cv2
import numpy as np


def _smooth_gaps(mask, maximum):
    result = mask.copy()
    good = np.flatnonzero(mask)
    for first, last in zip(good[:-1], good[1:]):
        if last - first - 1 <= maximum:
            result[first:last + 1] = True
    return result


def _fit_seam(edge, s, t, seed, radius, floor, fit_rows):
    cols = np.flatnonzero(np.abs(s - seed) <= radius)
    if cols.size < 3:
        return None
    values = edge[:, cols]
    indices = np.argmax(values, axis=1)
    strength = values[np.arange(len(t)), indices]
    positions = s[cols[indices]]
    good = fit_rows & (strength >= floor)
    if good.sum() < max(8, fit_rows.sum() * .45):
        return None
    for _ in range(3):
        slope, intercept = np.polyfit(t[good], positions[good], 1)
        residual = np.abs(positions - (slope * t + intercept))
        noise = float(np.median(residual[good]))
        good &= residual <= max(2.5, noise * 3)
        if good.sum() < 8:
            return None
    if abs(slope) > .18:
        return None
    return float(slope), float(intercept), float(good.sum() / max(1, fit_rows.sum()))


def refine_centerline_spine(image, points, existing_box, existing_polygon=None, *, context=None):
    """Return ``(box, polygon, audit)``; accepted=False means exact fallback.

    Supports horizontal/vertical books and modest perspective skew. Colour
    thresholds derive from this oriented ROI, not a global image threshold.
    No OCR text, catalogue, confidence, title selection or hardware is changed.
    ``confidence`` is a heuristic evidence score, not a calibrated probability.
    """
    audit = dict(method='ocr_centerline_local_seams_v1', accepted=False,
                 anchor_semantics='unknown_text_region', confidence=0.0,
                 confidence_semantics='heuristic_not_probability')

    def fallback(reason):
        audit['reason'] = reason
        return existing_box, existing_polygon, audit

    try:
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            return fallback('invalid_image')
        h, w = image.shape[:2]
        pts = np.asarray(points, dtype=float)
        box = np.asarray(existing_box, dtype=float)
        if pts.shape != (4, 2) or box.shape != (4,) or not np.isfinite(pts).all() or not np.isfinite(box).all():
            return fallback('invalid_geometry')
        if w < 20 or h < 20 or box[2] <= box[0] or box[3] <= box[1]:
            return fallback('invalid_geometry')
        if np.any(pts < 0) or np.any(pts[:, 0] > w - 1) or np.any(pts[:, 1] > h - 1):
            return fallback('ocr_outside_image')
        if not cv2.isContourConvex(pts.astype(np.float32)):
            return fallback('nonconvex_ocr_quad')
        edges = np.roll(pts, -1, axis=0) - pts
        lengths = np.linalg.norm(edges, axis=1)
        pair = 0 if lengths[0] + lengths[2] >= lengths[1] + lengths[3] else 1
        first, second = edges[pair], -edges[pair + 2]
        if min(lengths) < 2 or np.dot(first, second) <= 0:
            return fallback('degenerate_ocr_quad')
        u = first / np.linalg.norm(first) + second / np.linalg.norm(second)
        u /= np.linalg.norm(u)
        if u[np.argmax(np.abs(u))] < 0:
            u = -u
        v = np.array([-u[1], u[0]])
        origin = pts.mean(axis=0)
        projected = np.column_stack(((pts - origin) @ u, (pts - origin) @ v))
        text_length, text_width = np.ptp(projected, axis=0)
        if text_length < 18 or text_width < 3 or text_length / text_width < 2.3:
            return fallback('ambiguous_short_text_direction')
        old_poly = np.asarray(existing_polygon if existing_polygon is not None else
                              [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]], dtype=float)
        if old_poly.shape != (4, 2) or not np.isfinite(old_poly).all():
            return fallback('invalid_existing_polygon')
        old_t, old_s = (old_poly - origin) @ u, (old_poly - origin) @ v
        old_length, old_width = np.ptp(old_t), np.ptp(old_s)
        if old_length < old_width * .7:
            return fallback('text_axis_conflicts_with_existing_spine')
        # Full visible long-axis reach is intentional: short text must not
        # define the book's longitudinal ends. Search width stays local.
        bounds = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=float)
        frame_t, frame_s = (bounds - origin) @ u, (bounds - origin) @ v
        t_lo, t_hi = float(frame_t.min()), float(frame_t.max())
        reach = min(np.ptp(frame_s) * .22, max(text_width * 4, old_width * .9, 20))
        s_lo, s_hi = -reach, reach
        step = max(1.0, (t_hi - t_lo) / 2048, (s_hi - s_lo) / 768)
        t = np.arange(t_lo, t_hi + step * .1, step, dtype=np.float32)
        s = np.arange(s_lo, s_hi + step * .1, step, dtype=np.float32)
        xx = origin[0] + t[:, None] * u[0] + s[None, :] * v[0]
        yy = origin[1] + t[:, None] * u[1] + s[None, :] * v[1]
        valid = (xx >= 0) & (xx <= w - 1) & (yy >= 0) & (yy <= h - 1)
        # Crop before Lab conversion; no persistent full-frame allocation here.
        x0, x1 = max(0, int(np.floor(xx.min()))), min(w, int(np.ceil(xx.max())) + 1)
        y0, y1 = max(0, int(np.floor(yy.min()))), min(h, int(np.ceil(yy.max())) + 1)
        crop = image[y0:y1, x0:x1]
        if not crop.size:
            return fallback('empty_roi')
        lab = cv2.GaussianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32), (3, 3), 0)
        patch = cv2.remap(lab, (xx - x0).astype(np.float32), (yy - y0).astype(np.float32),
                          cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        radius = max(1, int(round(3 / step)))
        normal_edge = np.zeros(valid.shape, np.float32)
        normal_edge[:, radius:-radius] = np.linalg.norm(patch[:, 2 * radius:] - patch[:, :-2 * radius], axis=2)
        normal_edge[~valid] = 0
        fit_rows = (t >= min(old_t.min(), projected[:, 0].min()) - text_width) & (t <= max(old_t.max(), projected[:, 0].max()) + text_width)
        anchor_rows = (t >= projected[:, 0].min()) & (t <= projected[:, 0].max())
        if anchor_rows.sum() < 8:
            return fallback('insufficient_anchor_samples')
        sample = normal_edge[fit_rows][valid[fit_rows]]
        if not sample.size:
            return fallback('empty_roi')
        noise = float(np.median(sample))
        mad = float(np.median(np.abs(sample - noise)))
        # The 5 Lab-unit floor only rejects almost flat/noise-only regions;
        # all stronger decisions depend on local contrast and supported runs.
        floor = max(5.0, noise + 3 * 1.4826 * mad)
        profile = np.median(normal_edge[anchor_rows], axis=0)
        gap = max(2.0, text_width * .08)
        low_s, high_s = projected[:, 1].min(), projected[:, 1].max()
        candidates = []
        for side in (0, 1):
            indices = np.flatnonzero((s < low_s - gap if side == 0 else s > high_s + gap) & (profile >= floor))
            if not indices.size:
                return fallback('insufficient_side_seams')
            # Pick the nearest supported seam outside the OCR band, not the
            # strongest distant book boundary. Local maxima avoid its halo.
            local = cv2.dilate(profile.reshape(1, -1), np.ones((1, max(3, 2 * radius + 1)), np.uint8)).ravel()
            peaks = indices[profile[indices] >= local[indices] - 1e-5]
            if not peaks.size:
                return fallback('insufficient_side_seams')
            selected = peaks[np.argmax(s[peaks])] if side == 0 else peaks[np.argmin(s[peaks])]
            candidates.append(float(s[selected]))
        tracking_radius = max(5.0, text_width * .5, old_width * .25)
        fits = [_fit_seam(normal_edge, s, t, seed, tracking_radius, floor, fit_rows) for seed in candidates]
        if any(fit is None for fit in fits):
            return fallback('weak_side_fit')
        lower = fits[0][0] * t + fits[0][1]
        upper = fits[1][0] * t + fits[1][1]
        width = upper - lower
        if np.min(width[anchor_rows]) < text_width + gap or np.median(width[anchor_rows]) > max(old_width * 1.5, text_width * 5):
            return fallback('invalid_side_band')
        side_strength, side_valid = [], []
        for line in (lower, upper):
            cols = np.clip(np.rint((line - s_lo) / step).astype(int), radius, len(s) - radius - 1)
            neighbourhood = np.arange(-radius, radius + 1)
            indices = np.clip(cols[:, None] + neighbourhood, 0, len(s) - 1)
            strength = normal_edge[np.arange(len(t))[:, None], indices].max(axis=1)
            side_strength.append(strength)
            side_valid.append(valid[np.arange(len(t)), cols])
        joint_raw = (side_strength[0] >= floor) & (side_strength[1] >= floor) & side_valid[0] & side_valid[1]
        joint = _smooth_gaps(joint_raw, max(2, min(12, int(text_width * .2 / step))))
        if joint_raw[anchor_rows].mean() < .65:
            return fallback('sides_do_not_support_anchor')
        central = int(np.argmin(np.abs(t)))
        near = np.flatnonzero(joint & anchor_rows)
        center_index = near[np.argmin(np.abs(near - central))]
        left = right = int(center_index)
        while left > 0 and joint[left - 1]: left -= 1
        while right + 1 < len(t) and joint[right + 1]: right += 1
        if t[left] > projected[:, 0].min() or t[right] < projected[:, 0].max():
            return fallback('disconnected_side_run')
        # Centerline plus 14 parallel interior lines seek a broad end cap;
        # a printed letter on one line cannot supply this median transition.
        fractions = np.linspace(.15, .85, 15)
        interior_s = lower[:, None] + width[:, None] * fractions[None, :]
        sample_x = ((interior_s - s_lo) / step).astype(np.float32)
        sample_y = np.broadcast_to(np.arange(len(t), dtype=np.float32)[:, None], sample_x.shape).copy()
        interior = cv2.remap(patch, sample_x, sample_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        end_score = np.zeros(len(t), np.float32)
        end_score[radius:-radius] = np.median(np.linalg.norm(interior[2 * radius:] - interior[:-2 * radius], axis=2), axis=1)
        score_inside = end_score[left:right + 1]
        end_noise = float(np.median(score_inside))
        end_floor = max(5.0, end_noise + 3 * 1.4826 * float(np.median(np.abs(score_inside - end_noise))))
        ends, clipped = [], []
        for side, current in ((0, left), (1, right)):
            search = max(4, int(min(text_width * .65, 35) / step))
            lo, hi = max(radius, current - search), min(len(t) - radius, current + search + 1)
            allowed = np.arange(lo, hi)
            allowed = allowed[t[allowed] < projected[:, 0].min() - gap] if side == 0 else allowed[t[allowed] > projected[:, 0].max() + gap]
            if allowed.size and end_score[allowed].max() >= end_floor:
                chosen = int(allowed[np.argmax(end_score[allowed])])
                ends.append(chosen)
                clipped.append(False)
            elif (current <= radius + 1 if side == 0 else current >= len(t) - radius - 2):
                ends.append(current)
                clipped.append(True)
            else:
                audit['candidate_longitudinal_run'] = [round(float(t[left]), 2), round(float(t[right]), 2)]
                return fallback('weak_end_support')
        a, b = ends
        if b <= a or t[b] - t[a] < text_length + gap * 2:
            return fallback('ends_cut_anchor')
        audit['candidate_longitudinal_run'] = [round(float(t[left]), 2), round(float(t[right]), 2)]
        # An interior label may erase side contrast briefly and create an end
        # transition. Substantial contraction of a previous supported extent is
        # therefore a review candidate, not an automatic correction.
        half_width = float(np.median(width[anchor_rows])) * .5
        if t[a] > old_t.min() + half_width or t[b] < old_t.max() - half_width:
            audit['candidate_image_longitudinal_extent'] = [float(t[a]), float(t[b])]
            return fallback('large_extent_contraction_requires_review')
        # Independent end context: outside the candidate cap should resemble
        # the local flanking background and remain quiet. A broad cover colour
        # panel alone supplies neither this evidence nor a physical book end.
        end_context = []
        for side, index in ((0, a), (1, b)):
            if clipped[side]:
                end_context.append(dict(clipped=True))
                continue
            distance = max(3, int(min(18, float(width[index]) * .2) / step))
            sign = -1 if side == 0 else 1
            outside = index + sign * np.arange(distance, distance * 2 + 1)
            inside = index - sign * np.arange(distance, distance * 2 + 1)
            if outside.min() < 0 or outside.max() >= len(t) or inside.min() < 0 or inside.max() >= len(t):
                return fallback('insufficient_end_background')
            after = np.median(interior[outside].reshape(-1, 3), axis=0)
            before = np.median(interior[inside].reshape(-1, 3), axis=0)
            transition = float(np.linalg.norm(before - after))
            flank_s = np.column_stack((lower[outside] - width[outside] * .2,
                                       upper[outside] + width[outside] * .2))
            flank_x = ((flank_s - s_lo) / step).astype(np.float32)
            flank_y = np.broadcast_to(outside[:, None].astype(np.float32), flank_x.shape).copy()
            if (flank_x < 0).any() or (flank_x > len(s) - 1).any():
                return fallback('insufficient_end_background')
            flank = cv2.remap(patch, flank_x, flank_y, cv2.INTER_LINEAR)
            agreement = max(float(np.linalg.norm(np.median(flank[:, side], axis=0) - after)) for side in (0, 1))
            spread = float(np.quantile(np.linalg.norm(interior[outside].reshape(-1, 3) - after, axis=1), .85))
            audit_limit = max(end_floor, transition * .65)
            end_context.append(dict(transition=round(transition, 3), flank_disagreement=round(agreement, 3),
                                    outside_spread=round(spread, 3), limit=round(audit_limit, 3)))
            if transition < end_floor or agreement > audit_limit or spread > audit_limit:
                audit['end_context'] = end_context
                return fallback('end_is_not_supported_background_transition')
        normal_coords = [lower[a], upper[a], upper[b], lower[b]]
        long_coords = [t[a], t[a], t[b], t[b]]
        polygon = [np.clip(origin + tt * u + ss * v, [0, 0], [w - 1, h - 1]).round().astype(int).tolist()
                   for tt, ss in zip(long_coords, normal_coords)]
        contour = np.asarray(polygon, dtype=np.float32)
        if not cv2.isContourConvex(contour) or any(cv2.pointPolygonTest(contour, tuple(map(float, p)), True) < -1.5 for p in pts):
            return fallback('candidate_cuts_anchor')
        refined = [min(p[0] for p in polygon), min(p[1] for p in polygon), max(p[0] for p in polygon), max(p[1] for p in polygon)]
        confidence = min(fits[0][2], fits[1][2], float(joint_raw[a:b + 1].mean()))
        audit.update(confidence=round(confidence, 4), candidate_box=refined,
                     candidate_polygon=polygon, end_context=end_context)
        # Small anchors cannot distinguish a title from an author/edition label.
        # Keep semantic selection unchanged and demand stronger image support.
        required_support = .90 if text_length < old_length * .25 else .85
        audit['required_side_support'] = required_support
        if confidence < required_support:
            return fallback('weak_candidate_confidence')
        audit.update(accepted=True, reason='paired_side_run_and_end_support', confidence=round(confidence, 4),
                     axis=[round(float(q), 5) for q in u], roi_step=float(step),
                     local_side_noise=round(noise, 3), local_side_threshold=round(floor, 3),
                     local_end_threshold=round(end_floor, 3), side_fits=[list(f) for f in fits],
                     ocr_longitudinal_extent=[float(projected[:, 0].min()), float(projected[:, 0].max())],
                     image_longitudinal_extent=[float(t[a]), float(t[b])],
                     visible_region_clipped=any(clipped),
                     centerline_origin=origin.tolist(), context_reused=False,
                     semantic_selection_unchanged=True)
        return refined, polygon, audit
    except (ValueError, TypeError, IndexError, cv2.error, np.linalg.LinAlgError):
        return fallback('invalid_or_unstable_geometry')
