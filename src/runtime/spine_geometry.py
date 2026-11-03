"""Image-derived spine seams; no title catalogue or registered book positions."""
import cv2
import numpy as np


def vertical_seams(image):
    return spine_edges(image)[0]


def spine_edges(image):
    """Share line detection and Lab colours across the selected spines."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    detector = cv2.createLineSegmentDetector()
    detected = detector.detect(gray)[0]
    lines = np.empty((0, 4), dtype=np.float32) if detected is None else detected.reshape(-1, 4)
    dx = np.abs(lines[:, 2] - lines[:, 0])
    dy = np.abs(lines[:, 3] - lines[:, 1])
    horizontal = lines[(dx >= image.shape[1] * 0.015) & (dy <= dx * 0.12)]
    # Equal-luminance covers can have a clear colour seam absent in grayscale.
    chroma = cv2.normalize(lab[:, :, 1], None, 0, 255, cv2.NORM_MINMAX)
    coloured = detector.detect(chroma)[0]
    if coloured is not None:
        lines = np.concatenate((lines, coloured.reshape(-1, 4)))
        colour_lines = coloured.reshape(-1, 4)
        dx = np.abs(colour_lines[:, 2] - colour_lines[:, 0])
        dy = np.abs(colour_lines[:, 3] - colour_lines[:, 1])
        horizontal = np.concatenate((horizontal, colour_lines[
            (dx >= image.shape[1] * 0.015) & (dy <= dx * 0.12)]))
    dy = np.abs(lines[:, 3] - lines[:, 1])
    keep = (dy >= image.shape[0] * 0.075) & (np.abs(lines[:, 2] - lines[:, 0]) <= dy * 0.12)
    return lines[keep], horizontal, lab


def refine_ends(edges, title, box):
    """Use seam endpoints for the top and supported background for the bottom.

    Internal labels have edges too; a bottom candidate must lead into a broad,
    quiet band below the spine. Missing evidence retains the original extent.
    """
    vertical, horizontal, lab = edges
    h, w = lab.shape[:2]
    tx1, ty1, tx2, ty2 = title
    bx1, top, bx2, bottom = box
    bw = bx2 - bx1
    cy = (ty1 + ty2) / 2
    starts = []
    ends = []
    for x1, y1, x2, y2 in vertical:
        lo, hi = sorted((float(y1), float(y2)))
        if min(hi, ty2) - max(lo, ty1) < (ty2 - ty1) * 0.12:
            continue
        x = float(x1 + (x2 - x1) * (cy - y1) / (y2 - y1))
        if min(abs(x - bx1), abs(x - bx2)) < bw * 0.20 and not tx1 <= x <= tx2:
            starts.append(lo)
            ends.append(hi)
    upper, lower = [], []
    strip = max(15, int(h * 0.028))
    cx = (bx1 + bx2) / 2
    for x1, y1, x2, y2 in horizontal:
        overlap = max(0, min(max(x1, x2), bx2) - max(min(x1, x2), bx1))
        if overlap < max(24, bw * 0.30):
            continue
        y = float((y1 + y2) / 2)
        if starts and 0 < y < ty1 - 4 and abs(y - min(starts)) < h * 0.02:
            upper.append(y)
        if not ty2 + h * 0.01 < y < min(bottom + 5, h - strip - 4):
            continue
        ya = int(round(y)) + 3
        patch = lab[ya:ya + strip, max(0, int(cx - bw * 0.9)):min(w, int(cx + bw * 0.9))].astype(np.float32)
        if not patch.size:
            continue
        background = np.median(patch.reshape(-1, 3), axis=0)
        spread = np.percentile(np.linalg.norm(patch - background, axis=2), 85)
        before = lab[max(0, int(y) - 15):int(y) - 3,
                     bx1 + int(bw * 0.15):bx2 - int(bw * 0.15)]
        if not before.size:
            continue
        transition = np.linalg.norm(np.median(before.reshape(-1, 3), axis=0) - background)
        if spread < 18 and transition > 8:
            lower.append(y)
    if upper:
        top = int(round(min(upper, key=lambda y: abs(y - min(starts)))))
    elif starts and min(starts) < h * 0.015:
        top = 0
    if lower:
        first = min(lower)
        bottom = int(round(max(y for y in lower if y - first < h * 0.012)))
    elif ends and max(ends) > h * 0.985:
        bottom = h - 1
    return [bx1, top, bx2, bottom]


def refine_spine(edges, title, box, image_shape, title_points=None):
    extent = refine_ends(edges, title, box)
    return refine_sides(edges[0], title, extent, image_shape, title_points)


def refine_sides(lines, title, box, image_shape, title_points=None, text_tolerance=0, fit_audit=None):
    """Fit nearby long seams; retain the original sides if evidence is absent."""
    h, w = image_shape[:2]
    if fit_audit is not None:
        fit_audit.update(side_fit_count=0)
    tx1, ty1, tx2, ty2 = title
    cy = (ty1 + ty2) / 2
    gap = max(3, w * 0.006)
    if title_points is not None:
        title_vertices = np.asarray(title_points, dtype=float)
        intersections = []
        for first, second in zip(title_vertices, np.roll(title_vertices, -1, axis=0)):
            if min(first[1], second[1]) <= cy <= max(first[1], second[1]) and abs(second[1] - first[1]) > 1e-6:
                intersections.append(first[0] + (second[0] - first[0]) * (cy - first[1]) / (second[1] - first[1]))
        if len(intersections) >= 2:
            tx1, tx2 = min(intersections), max(intersections)
            gap = max(2, (tx2 - tx1) * 0.06)
    reach = max((tx2 - tx1) * 3, w * 0.10)
    eligible = []
    for line in lines:
        x1, y1, x2, y2 = map(float, line)
        dy = abs(y2 - y1)
        overlap = max(0, min(max(y1, y2), ty2) - max(min(y1, y2), ty1))
        if dy < max(h * 0.075, (ty2 - ty1) * 0.20) or overlap < min(dy * 0.25, (ty2 - ty1) * 0.12):
            continue
        slope = (x2 - x1) / (y2 - y1)
        x = x1 + slope * (cy - y1)
        eligible.append((x, line, dy))

    fits = []
    for side in ('left', 'right'):
        candidates = [entry for entry in eligible if
                      (tx1 - reach < entry[0] < tx1 - gap if side == 'left'
                       else tx2 + gap < entry[0] < tx2 + reach)]
        if not candidates:
            fits.append(None)
            continue
        anchor = (max if side == 'left' else min)(candidates, key=lambda entry: entry[0])[0]
        group = [entry for entry in candidates if abs(entry[0] - anchor) <= max(4, w * 0.004)]
        points = np.asarray([point for _, line, _ in group
                             for point in ((line[1], line[0]), (line[3], line[2]))], dtype=float)
        slope, intercept = np.polyfit(points[:, 0], points[:, 1], 1)
        # Reject extrapolations that would cut into the detected title.
        xs = slope * np.array([ty1, ty2]) + intercept
        if title_points is not None:
            distances = title_vertices[:, 0] - (slope * title_vertices[:, 1] + intercept)
            cuts_title = (distances.min() <= -text_tolerance if side == 'left'
                          else distances.max() >= text_tolerance)
        else:
            cuts_title = (side == 'left' and xs.max() >= tx1) or (side == 'right' and xs.min() <= tx2)
        if cuts_title:
            fits.append(None)
        else:
            fits.append((slope, intercept))

    bx1, by1, bx2, by2 = box
    left, right = fits
    left_x = [bx1, bx1] if left is None else [left[0] * y + left[1] for y in (by1, by2)]
    right_x = [bx2, bx2] if right is None else [right[0] * y + right[1] for y in (by1, by2)]
    if any(rx - lx < max(8, tx2 - tx1) for lx, rx in zip(left_x, right_x)):
        return box, None
    polygon = [[int(round(np.clip(x, 0, w - 1))), y] for x, y in
               ((left_x[0], by1), (right_x[0], by1), (right_x[1], by2), (left_x[1], by2))]
    refined = [min(p[0] for p in polygon), by1, max(p[0] for p in polygon), by2]
    # A line from a neighbouring object must not expand a plausible baseline
    # into another spine, especially when the old height crosses a shelf.
    expansion = max(gap, (bx2 - bx1) * 0.20)
    if refined[0] < bx1 - expansion or refined[2] > bx2 + expansion:
        return box, None
    if fit_audit is not None:
        fit_audit.update(side_fit_count=int(left is not None)+int(right is not None))
    return refined, polygon if left is not None or right is not None else None


def refine_flat_spine(image, points, box, edges=None):
    """Fit a flat spine in rotated coordinates and return original pixels."""
    h, w = image.shape[:2]
    rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if edges is None:
        edges = spine_edges(rotated)
    pts = np.asarray([[h - 1 - float(y), float(x)] for x, y in points])
    title = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
    x1, y1, x2, y2 = box
    rotated_box = [h - 1 - y2, x1, h - 1 - y1, x2]
    refined, polygon = refine_spine(edges, title, rotated_box, rotated.shape, pts)
    if polygon is None:
        return box, None
    # A cropped long book has no visible end cap. Extend only when both fitted
    # sides continue as image edges all the way to the corresponding frame.
    lab = edges[2]
    for endpoint, target in ((0, 0), (1, rotated.shape[0] - 1)):
        current = polygon[0][1] if endpoint == 0 else polygon[2][1]
        if abs(target - current) < 3:
            continue
        left_points, right_points = (polygon[0], polygon[3]), (polygon[1], polygon[2])
        snapped = []
        valid = True
        for y in np.linspace(current, target, 4)[1:]:
            profile = np.median(lab[max(0, int(y) - 6):min(lab.shape[0], int(y) + 7)], axis=0).astype(np.float32)
            delta = np.linalg.norm(profile[6:] - profile[:-6], axis=1)
            delta = np.pad(delta, (3, 3))
            positions = []
            for first, last in (left_points, right_points):
                slope = (last[0] - first[0]) / max(1, last[1] - first[1])
                x = first[0] + slope * (y - first[1])
                radius = max(6, (refined[2] - refined[0]) * 0.18)
                lo, hi = max(0, int(x - radius)), min(len(delta), int(x + radius) + 1)
                if hi <= lo or float(delta[lo:hi].max()) < 12:
                    valid = False
                    break
                positions.append(lo + int(np.argmax(delta[lo:hi])))
            if not valid or positions[1] - positions[0] < max(8, title[2] - title[0]) * 0.60:
                valid = False
                break
            snapped = positions
        if valid:
            if endpoint == 0:
                polygon[0], polygon[1] = [snapped[0], target], [snapped[1], target]
            else:
                polygon[3], polygon[2] = [snapped[0], target], [snapped[1], target]
    mapped = [[int(ry), int(h - 1 - rx)] for rx, ry in polygon]
    return [min(p[0] for p in mapped), min(p[1] for p in mapped),
            max(p[0] for p in mapped), max(p[1] for p in mapped)], mapped
