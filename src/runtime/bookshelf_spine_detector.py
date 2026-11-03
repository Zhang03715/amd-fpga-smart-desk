"""Realtime traditional-CV book-spine candidate detector.

Controls:
  Q / Esc  quit
  S        save current frame, overlay, edges and mask
  R        interactively select the bookshelf ROI
  C        clear the ROI and use the full frame
  D        toggle the debug mosaic
  O        cycle upright / flat / mixed detection
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--min-height", type=float, default=0.28)
    parser.add_argument("--max-width", type=float, default=0.24)
    parser.add_argument(
        "--orientation",
        choices=("upright", "flat", "mixed"),
        default="upright",
        help="initial book orientation mode",
    )
    parser.add_argument("--save-dir", type=Path, default=Path("captures"))
    return parser.parse_args()


def odd(value: int) -> int:
    return max(3, value | 1)


def merge_boxes(boxes: list[tuple[int, int, int, int]], frame_w: int):
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b[0])
    merged = [list(boxes[0])]
    gap_limit = max(3, int(frame_w * 0.006))
    for x, y, w, h in boxes[1:]:
        px, py, pw, ph = merged[-1]
        overlap_y = max(0, min(py + ph, y + h) - max(py, y))
        min_h = max(1, min(ph, h))
        if x <= px + pw + gap_limit and overlap_y / min_h > 0.55:
            x2 = max(px + pw, x + w)
            y2 = max(py + ph, y + h)
            merged[-1] = [min(px, x), min(py, y), x2 - min(px, x), y2 - min(py, y)]
        else:
            merged.append([x, y, w, h])
    return [tuple(b) for b in merged]


def cluster_vertical_lines(lines, width: int, height: int):
    samples = []
    if lines is None:
        return []
    for line in np.asarray(lines).reshape(-1, 4):
        x1, y1, x2, y2 = map(int, line)
        dy = abs(y2 - y1)
        dx = abs(x2 - x1)
        if dy < height * 0.18 or dx > max(5, dy * 0.16):
            continue
        samples.append(((x1 + x2) / 2.0, dy, min(y1, y2), max(y1, y2)))
    if not samples:
        return []
    samples.sort(key=lambda item: item[0])
    tolerance = max(5, int(width * 0.006))
    groups = []
    for sample in samples:
        if not groups or sample[0] - groups[-1][-1][0] > tolerance:
            groups.append([sample])
        else:
            groups[-1].append(sample)
    boundaries = []
    for group in groups:
        weights = np.array([item[1] for item in group], dtype=np.float32)
        xs = np.array([item[0] for item in group], dtype=np.float32)
        x = int(round(float(np.average(xs, weights=weights))))
        y1 = int(np.percentile([item[2] for item in group], 25))
        y2 = int(np.percentile([item[3] for item in group], 75))
        score = float(weights.sum())
        boundaries.append((x, y1, y2, score))
    return boundaries


def detect_vertical_spines(image: np.ndarray, min_height_ratio: float, max_width_ratio: float):
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    enhanced = cv2.GaussianBlur(enhanced, (5, 5), 0)

    grad_x = cv2.convertScaleAbs(cv2.Scharr(enhanced, cv2.CV_32F, 1, 0))
    edges = cv2.Canny(enhanced, 45, 130, L2gradient=True)

    # Keep only long near-vertical structures. Unlike the previous close operation,
    # this does not glue neighbouring books into one large component.
    vertical_len = odd(max(11, int(h * 0.12)))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_len))
    mask = cv2.morphologyEx(edges, cv2.MORPH_OPEN, vertical_kernel)
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 5)), iterations=1)

    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 360.0,
        threshold=max(24, int(h * 0.09)),
        minLineLength=max(30, int(h * 0.18)),
        maxLineGap=max(10, int(h * 0.08)),
    )
    boundaries = cluster_vertical_lines(lines, w, h)
    boundary_mask = np.zeros_like(mask)
    for x, y1, y2, _ in boundaries:
        cv2.line(boundary_mask, (x, max(0, y1)), (x, min(h - 1, y2)), 255, 2)
    mask = cv2.bitwise_or(mask, boundary_mask)

    min_h = int(h * min_height_ratio)
    max_w = int(w * max_width_ratio)
    min_w = max(9, int(w * 0.012))
    boxes: list[tuple[int, int, int, int]] = []
    strong = [item for item in boundaries if item[3] >= h * 0.16]
    strong.sort(key=lambda item: item[0])
    for left, right in zip(strong, strong[1:]):
        lx, ly1, ly2, _ = left
        rx, ry1, ry2, _ = right
        bw = rx - lx
        if bw < min_w or bw > max_w:
            continue
        y1 = max(0, min(ly1, ry1) - int(h * 0.03))
        y2 = min(h - 1, max(ly2, ry2) + int(h * 0.03))
        bh = y2 - y1
        if bh < min_h:
            continue
        # Reject almost textureless gaps while retaining light-coloured spines.
        texture = float(np.mean(grad_x[y1:y2, lx:rx]))
        if texture < 7.0:
            continue
        boxes.append((lx, y1, bw, bh))

    return boxes, grad_x, mask


def detect_spines(
    image: np.ndarray,
    min_height_ratio: float,
    max_width_ratio: float,
    orientation: str = "upright",
):
    """Detect upright books, flat books, or both.

    Each returned item is ``(x, y, width, height, kind)``.  Flat candidates
    are found by rotating the ROI, reusing the upright detector, and then
    applying stricter geometry checks to suppress shelves and long text rows.
    """
    vertical, edge_v, mask_v = detect_vertical_spines(image, min_height_ratio, max_width_ratio)

    if orientation == "upright":
        return [(*box, "upright") for box in vertical], edge_v, mask_v

    rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    horizontal_r, edge_h_r, mask_h_r = detect_vertical_spines(
        rotated, min_height_ratio, max_width_ratio
    )
    original_h, original_w = image.shape[:2]
    horizontal = []
    for xr, yr, wr, hr in horizontal_r:
        # Inverse mapping from a clockwise-rotated rectangle.
        x = yr
        y = original_h - (xr + wr)
        bw, bh = hr, wr
        aspect = bw / max(1, bh)
        # A visible flat-book spine is wide but should not span nearly the
        # whole camera image (that is normally a shelf board or screen edge).
        if (
            2.2 <= aspect <= 14.0
            and 0.10 * original_w <= bw <= 0.68 * original_w
            and 0.018 * original_h <= bh <= 0.20 * original_h
        ):
            horizontal.append((x, y, bw, bh))

    edge_h = cv2.rotate(edge_h_r, cv2.ROTATE_90_COUNTERCLOCKWISE)
    mask_h = cv2.rotate(mask_h_r, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if orientation == "flat":
        return [(*box, "flat") for box in horizontal], edge_h, mask_h

    combined_edge = cv2.max(edge_v, edge_h)
    combined_mask = cv2.max(mask_v, mask_h)
    labelled = [(*box, "upright") for box in vertical]
    labelled.extend((*box, "flat") for box in horizontal)
    return labelled, combined_edge, combined_mask


def fit_panel(img: np.ndarray, width: int, height: int) -> np.ndarray:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    scale = min(width / img.shape[1], height / img.shape[0])
    resized = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    y = (height - resized.shape[0]) // 2
    x = (width - resized.shape[1]) // 2
    canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return canvas


def main() -> None:
    args = parse_args()
    args.save_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open camera index {args.camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    window = "Traditional Book Spine Candidates"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1280, 760)
    roi = None
    orientation = args.orientation
    show_debug = True
    last_parts = None
    fps = 0.0
    tick = time.perf_counter()
    frames = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        frames += 1
        now = time.perf_counter()
        if now - tick >= 0.5:
            fps = frames / (now - tick)
            tick, frames = now, 0

        if roi is None:
            rx, ry, rw, rh = 0, 0, frame.shape[1], frame.shape[0]
        else:
            rx, ry, rw, rh = roi
        crop = frame[ry : ry + rh, rx : rx + rw]
        boxes, edges, mask = detect_spines(
            crop, args.min_height, args.max_width, orientation
        )

        overlay = frame.copy()
        if roi is not None:
            cv2.rectangle(overlay, (rx, ry), (rx + rw, ry + rh), (255, 180, 0), 2)
        for index, (x, y, bw, bh, kind) in enumerate(boxes, 1):
            x1, y1 = x + rx, y + ry
            colour = (0, 255, 0) if kind == "upright" else (0, 165, 255)
            cv2.rectangle(overlay, (x1, y1), (x1 + bw, y1 + bh), colour, 2)
            cv2.putText(overlay, str(index), (x1 + 3, max(20, y1 + 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)

        cv2.putText(overlay, f"mode={orientation}  candidates={len(boxes)}  fps={fps:.1f}", (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (20, 230, 255), 2)
        cv2.putText(overlay, "Q quit | S save | R ROI | C clear | D debug | O orientation", (18, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 230, 255), 1)

        if show_debug:
            ph, pw = 260, 420
            top = fit_panel(overlay, pw * 2, ph * 2)
            edge_panel = fit_panel(edges, pw, ph)
            mask_panel = fit_panel(mask, pw, ph)
            debug_row = np.hstack((edge_panel, mask_panel))
            display = np.vstack((top, debug_row))
        else:
            display = overlay
        last_parts = frame, overlay, edges, mask
        cv2.imshow(window, display)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("d"):
            show_debug = not show_debug
        elif key == ord("o"):
            modes = ("upright", "flat", "mixed")
            orientation = modes[(modes.index(orientation) + 1) % len(modes)]
            print(f"Orientation mode: {orientation}")
        elif key == ord("c"):
            roi = None
        elif key == ord("r"):
            selected = cv2.selectROI("Select bookshelf ROI and press Enter", frame, False, False)
            cv2.destroyWindow("Select bookshelf ROI and press Enter")
            if selected[2] > 20 and selected[3] > 20:
                roi = tuple(map(int, selected))
        elif key == ord("s") and last_parts is not None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            names = ("frame", "overlay", "edges", "mask")
            for name, image in zip(names, last_parts):
                cv2.imwrite(str(args.save_dir / f"{stamp}_{name}.png"), image)
            print(f"Saved capture set: {stamp}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
