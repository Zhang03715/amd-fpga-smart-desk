"""Conservative text-band evidence for experimental negative prompts.

Unknown never means same book. This module does not merge or resize regions.
"""
import math
import numpy as np


def text_band_relation(first, second):
    boxes = [np.asarray(box, float) for box in (first, second)]
    if any(b.shape != (4,2) or not np.isfinite(b).all() for b in boxes):
        return dict(relation='unknown', reason='invalid_text_geometry')
    axes = []
    for box in boxes:
        _, vectors = np.linalg.eigh(np.cov(box.T))
        u = vectors[:, -1]
        n = np.array([-u[1],u[0]])
        if np.ptp(box@u) < 2*max(1.,np.ptp(box@n)):
            return dict(relation='unknown', reason='weak_text_axis')
        axes.append((u,n))
    if abs(float(axes[0][0]@axes[1][0])) < math.cos(math.radians(10)):
        return dict(relation='unknown', reason='different_text_axes')
    ratios=[]
    for (_,n) in axes:
        x,y=[box@n for box in boxes]
        gap=max(float(y.min()-x.max()),float(x.min()-y.max()))
        scale=max(1.,min(float(np.ptp(x)),float(np.ptp(y))))
        ratios.append(gap/scale)
    # Each box gets 5% short-axis uncertainty; require disjointness under both axes.
    # This is text-band separation, not proof of a physical book seam.
    return dict(relation='separated_text_bands' if min(ratios)>.10 else 'unknown',
                reason='bilateral_normal_interval_gap', gap_ratios=ratios)
