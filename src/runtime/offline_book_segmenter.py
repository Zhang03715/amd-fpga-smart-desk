"""Offline book-spine segmentation experiment using only traditional OpenCV.

The detector scores *persistent* colour changes down a column.  A character
stroke only affects a short part of a column, while a real spine boundary is
usually visible through much of the shelf height.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def persistent_boundary_score(image: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    h, w = image.shape[:2]
    y1, y2 = int(h * 0.10), int(h * 0.88)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab = cv2.GaussianBlur(lab, (5, 5), 0)
    radius = max(2, int(w * 0.0025))
    delta = np.linalg.norm(
        lab[y1:y2, 2 * radius :] - lab[y1:y2, : -2 * radius], axis=2
    )

    # Median favours long continuous edges; the upper quartile recovers faint
    # boundaries that are partly hidden by labels or damaged book covers.
    score = 0.72 * np.median(delta, axis=0) + 0.28 * np.percentile(delta, 72, axis=0)
    score = np.pad(score, (radius, radius), mode="edge")
    sigma = max(2.0, w * 0.0022)
    score = cv2.GaussianBlur(score.reshape(1, -1), (0, 0), sigmaX=sigma).ravel()
    score = (score - score.min()) / max(1e-6, score.max() - score.min())
    return score, (y1, y2)


def select_peaks(score: np.ndarray, width: int) -> list[int]:
    local_window = max(9, int(width * 0.018)) | 1
    dilated = cv2.dilate(score.reshape(1, -1), np.ones((1, local_window), np.uint8)).ravel()
    threshold = max(0.18, float(np.median(score) + 0.72 * np.std(score)))
    candidates = np.flatnonzero((score >= dilated - 1e-6) & (score >= threshold))
    min_gap = max(10, int(width * 0.012))
    selected: list[int] = []
    for x in sorted(candidates.tolist(), key=lambda i: float(score[i]), reverse=True):
        if all(abs(x - old) >= min_gap for old in selected):
            selected.append(x)
    return sorted(selected)


def segment(image: np.ndarray):
    score, (y1, y2) = persistent_boundary_score(image)
    peaks = select_peaks(score, image.shape[1])
    boxes = []
    min_w = max(12, int(image.shape[1] * 0.012))
    max_w = int(image.shape[1] * 0.20)
    for left, right in zip(peaks, peaks[1:]):
        if min_w <= right - left <= max_w:
            boxes.append((left, y1, right - left, y2 - y1))
    return boxes, peaks, score, (y1, y2)


def render(image: np.ndarray):
    boxes, peaks, score, (y1, y2) = segment(image)
    out = image.copy()
    for x in peaks:
        cv2.line(out, (x, y1), (x, y2), (255, 80, 0), 2)
    for number, (x, y, w, h) in enumerate(boxes, 1):
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(out, str(number), (x + 3, y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(out, f"traditional candidates: {len(boxes)}", (18, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 255), 2)
    return out, boxes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("offline_results"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for path in args.images:
        image = cv2.imread(str(path))
        if image is None:
            print(f"Cannot read: {path}")
            continue
        overlay, boxes = render(image)
        target = args.output / f"{path.stem}_traditional.jpg"
        cv2.imwrite(str(target), overlay)
        print(f"{path.name}: {len(boxes)} candidates -> {target}")


if __name__ == "__main__":
    main()
