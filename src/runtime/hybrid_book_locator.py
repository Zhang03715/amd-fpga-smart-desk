"""Offline hybrid locator: OCR finds the title; classical CV expands to its spine."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from rapidocr_onnxruntime import RapidOCR

from offline_book_ocr import get_font, similarity
from offline_book_segmenter import persistent_boundary_score, select_peaks
from spine_geometry import refine_spine, refine_flat_spine, spine_edges


def title_bounds(points):
    pts = np.asarray(points, dtype=np.float32)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


class GeometryContext:
    """Lazy, request-local image preprocessing; never reuse between captures."""

    def __init__(self, image: np.ndarray):
        self.image = image
        self._rotated = None
        self._rotated_peaks = None
        self._blurred = {}
        self.audit = {"lab_blur_calls": 0, "rotation_calls": 0,
                      "rotated_boundary_calls": 0}

    @property
    def rotated(self):
        if self._rotated is None:
            self._rotated = cv2.rotate(self.image, cv2.ROTATE_90_CLOCKWISE)
            self.audit["rotation_calls"] += 1
        return self._rotated

    @property
    def rotated_peaks(self):
        if self._rotated_peaks is None:
            score, _ = persistent_boundary_score(self.rotated)
            self._rotated_peaks = select_peaks(score, self.rotated.shape[1])
            self.audit["rotated_boundary_calls"] += 1
        return self._rotated_peaks

    def blurred_lab(self, image):
        if image is self.image:
            key = "original"
        elif image is self._rotated:
            key = "rotated"
        else:
            raise ValueError("GeometryContext belongs to a different capture")
        if key not in self._blurred:
            self._blurred[key] = cv2.GaussianBlur(
                cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32), (5, 5), 0)
            self.audit["lab_blur_calls"] += 1
        return self._blurred[key]

    @property
    def retained_bytes(self):
        return sum(array.nbytes for array in self._blurred.values()) + (
            0 if self._rotated is None else self._rotated.nbytes)


def vertical_extent(image: np.ndarray, x1: int, x2: int, title_y1: float, title_y2: float, *, context=None):
    """Find the book top/bottom using colour transitions across its width."""
    h, w = image.shape[:2]
    margin = max(3, int((x2 - x1) * 0.12))
    xa, xb = max(0, x1 + margin), min(w, x2 - margin)
    if xb - xa < 8:
        xa, xb = max(0, x1), min(w, x2)
    lab = context.blurred_lab(image) if context is not None else cv2.GaussianBlur(
        cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32), (5, 5), 0)
    radius = max(3, int(h * 0.003))
    delta = np.linalg.norm(lab[2 * radius :, xa:xb] - lab[: -2 * radius, xa:xb], axis=2)
    score = 0.75 * np.median(delta, axis=1) + 0.25 * np.percentile(delta, 72, axis=1)
    score = np.pad(score, (radius, radius), mode="edge")
    score = cv2.GaussianBlur(
        score.reshape(-1, 1), (1, 0), sigmaX=0, sigmaY=max(2.0, h * 0.002)
    ).ravel()
    score = (score - score.min()) / max(1e-6, score.max() - score.min())
    window = max(11, int(h * 0.018)) | 1
    local = cv2.dilate(score.reshape(-1, 1), np.ones((window, 1), np.uint8)).ravel()
    threshold = max(0.16, float(np.median(score) + 0.65 * np.std(score)))
    candidates = np.flatnonzero((score >= local - 1e-6) & (score >= threshold)).tolist()
    above = [y for y in candidates if h * 0.025 < y < title_y1 - h * 0.015]
    below = [y for y in candidates if title_y2 + h * 0.015 < y < h * 0.985]
    # The nearest upper transition is normally the book top.  The lowest
    # lower transition retains call-number labels and reaches the shelf line.
    top = max(above) if above else max(0, int(title_y1 - h * 0.18))
    bottom = max(below) if below else min(h - 1, int(title_y2 + h * 0.35))
    if bottom - top < h * 0.35:
        bottom = min(h - 1, int(title_y2 + h * 0.45))
    return top, bottom


def expand_to_spine(image: np.ndarray, points, peaks: list[int], width: int, height: int, *, context=None):
    x1, y1, x2, y2 = title_bounds(points)
    cx = (x1 + x2) / 2
    # Ignore peaks crossing the OCR text itself: these usually come from glyphs.
    left = [x for x in peaks if x < x1 - width * 0.006]
    right = [x for x in peaks if x > x2 + width * 0.006]
    fallback_half = max((x2 - x1) * 1.25, width * 0.025)
    bx1 = max(0, int(max(left) if left else cx - fallback_half))
    bx2 = min(width - 1, int(min(right) if right else cx + fallback_half))
    # Reject implausibly narrow/wide adjacent peaks and use OCR-scaled fallback.
    bw = bx2 - bx1
    if bw < width * 0.018 or bw > width * 0.24:
        bx1 = max(0, int(cx - fallback_half))
        bx2 = min(width - 1, int(cx + fallback_half))
    by1, by2 = vertical_extent(image, bx1, bx2, y1, y2, context=context)
    return [bx1, by1, bx2, by2], [round(cx, 1), round((y1 + y2) / 2, 1)]


def locate_spine(image: np.ndarray, points, upright_peaks: list[int], *, context=None):
    """Restore a vertical or horizontal spine according to OCR-box direction."""
    h, w = image.shape[:2]
    pts = np.asarray(points, dtype=np.float32)
    span_x = float(pts[:, 0].max() - pts[:, 0].min())
    span_y = float(pts[:, 1].max() - pts[:, 1].min())
    center = [round(float(pts[:, 0].mean()), 1), round(float(pts[:, 1].mean()), 1)]
    if span_x <= span_y * 1.15:
        box, _ = expand_to_spine(image, points, upright_peaks, w, h, context=context)
        return box, center, "upright"

    # A horizontal title normally means a flat book. Rotate clockwise so the
    # existing vertical-spine algorithm can be reused without a second set of
    # thresholds, then map the result back to the original image.
    rotated = context.rotated if context is not None else cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    rotated_points = [[h - 1 - float(y), float(x)] for x, y in pts]
    if context is not None:
        rotated_peaks = context.rotated_peaks
    else:
        rotated_score, _ = persistent_boundary_score(rotated)
        rotated_peaks = select_peaks(rotated_score, rotated.shape[1])
    rbox, _ = expand_to_spine(
        rotated, rotated_points, rotated_peaks, rotated.shape[1], rotated.shape[0], context=context
    )
    rx1, ry1, rx2, ry2 = rbox
    # Refine the top/bottom directly in the original image. Restricting the
    # row score to the OCR title's x-range avoids unrelated short books and
    # shelf objects weakening a real horizontal spine boundary.
    ox1 = max(0, int(pts[:, 0].min()))
    ox2 = min(w, int(pts[:, 0].max()))
    margin = max(4, int((ox2 - ox1) * 0.04))
    xa, xb = min(w - 1, ox1 + margin), max(ox1 + margin + 1, ox2 - margin)
    lab = context.blurred_lab(image) if context is not None else cv2.GaussianBlur(
        cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32), (5, 5), 0)
    radius = max(2, int(h * 0.0025))
    row_delta = np.linalg.norm(lab[2 * radius :, xa:xb] - lab[: -2 * radius, xa:xb], axis=2)
    row_score = np.median(row_delta, axis=1)
    row_score = np.pad(row_score, (radius, radius), mode="edge")
    row_score = cv2.GaussianBlur(row_score.reshape(-1, 1), (1, 0), sigmaX=0, sigmaY=2.2).ravel()
    ty1, ty2 = float(pts[:, 1].min()), float(pts[:, 1].max())
    reach = int(h * 0.14)
    top_lo, top_hi = max(1, int(ty1) - reach), max(2, int(ty1) - 2)
    bot_lo, bot_hi = min(h - 2, int(ty2) + 2), min(h - 1, int(ty2) + reach)
    local = cv2.dilate(row_score.reshape(-1, 1), np.ones((11, 1), np.uint8)).ravel()
    threshold = float(np.median(row_score) + 0.45 * np.std(row_score))
    candidates = np.flatnonzero((row_score >= local - 1e-6) & (row_score >= threshold)).tolist()
    top_candidates = [y for y in candidates if top_lo <= y < top_hi]
    bottom_candidates = [y for y in candidates if bot_lo <= y < bot_hi]
    top = max(top_candidates) if top_candidates else top_lo + int(np.argmax(row_score[top_lo:top_hi]))
    bottom = min(bottom_candidates) if bottom_candidates else bot_lo + int(np.argmax(row_score[bot_lo:bot_hi]))
    # The rotated pass remains useful for the book's left/right extent.
    box = [ry1, top, ry2, bottom]
    return box, center, "flat"


def locate(path: Path, target: str, output: Path, threshold: float, *, draw_labels: bool = True, supplied_ocr=None, flat_seam_extent=False, geometry_cache=False, geometry_audit=None, all_texts=False):
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Cannot read {path}")
    h, w = image.shape[:2]
    if supplied_ocr is None:
        engine = RapidOCR()
        result, _ = engine(image)
    else:
        result = supplied_ocr
    scored = []
    for points, text, confidence in result or []:
        score = 0.0 if all_texts else similarity(target, text)
        if all_texts or score >= threshold:
            scored.append((points, text, float(confidence), score))
    if not scored:
        raise SystemExit(f"No OCR match for {target!r} in {path.name}")
    best = max(item[3] for item in scored)
    matches = scored if all_texts else [item for item in scored if item[3] >= best - 0.05]

    boundary_score, _ = persistent_boundary_score(image)
    peaks = select_peaks(boundary_score, w)
    edges = spine_edges(image)
    flat_edges = None
    context = GeometryContext(image) if geometry_cache else None
    records = []
    canvas = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(canvas)
    font = get_font(max(20, w // 45)) if draw_labels else None
    for index, (points, text, confidence, score) in enumerate(matches, 1):
        book_box, center, orientation = locate_spine(image, points, peaks, context=context)
        polygon = None
        extent_audit=None
        if orientation == "upright":
            book_box, polygon = refine_spine(edges, title_bounds(points), book_box, image.shape)
        else:
            if flat_edges is None:
                flat_edges = spine_edges(context.rotated if context is not None else cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE))
            book_box, polygon = refine_flat_spine(image, points, book_box, flat_edges)
            if flat_seam_extent:
                from flat_spine_extent import restore_flat_extent
                book_box,polygon,extent_audit=restore_flat_extent(points,book_box,polygon,edges[1],image.shape,edges[2])
        bx1, by1, bx2, by2 = book_box
        pts = [tuple(map(int, p)) for p in points]
        if polygon:
            corners = [tuple(point) for point in polygon]
            draw.line(corners + [corners[0]], fill=(20, 255, 30), width=6)
        else:
            draw.rectangle(book_box, outline=(20, 255, 30), width=6)
        draw.line(pts + [pts[0]], fill=(255, 40, 30), width=5)
        if draw_labels:
            draw.text((bx1, max(0, by1 - getattr(font, "size", 20) - 4)), f"{index} {text}", font=font, fill=(20, 255, 30), stroke_width=2, stroke_fill=(0, 0, 0))
        records.append({
            "text": text,
            "ocr_confidence": round(confidence, 4),
            "match_score": round(score, 4),
            "title_box": np.asarray(points, dtype=int).tolist(),
            "book_box": book_box,
            "spine_polygon": polygon,
            "flat_extent_audit": extent_audit,
            "boundary_method": ("rotated_seams" if polygon else "rotated_color_peaks") if orientation == "flat"
                               else ("seams_and_background" if polygon else "color_peaks_with_extent_check"),
            "visible_region_clipped": bool(polygon and any(x in (0, w - 1) or y in (0, h - 1) for x, y in polygon)),
            "location_center": center,
            "normalized_center": [round(center[0] / w, 4), round(center[1] / h, 4)],
            "orientation": orientation,
        })

    output.mkdir(parents=True, exist_ok=True)
    image_out = output / f"{path.stem}_hybrid.jpg"
    json_out = output / f"{path.stem}_hybrid.json"
    canvas.save(image_out, quality=95)
    json_out.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    if geometry_audit is not None:
        geometry_audit.update(enabled=bool(context), scope="one_capture_only",
                              retained_preprocess_bytes=context.retained_bytes if context else 0,
                              **(context.audit if context else {}))
    print(f"{path.name}: {len(records)} match(es) -> {image_out}")
    for record in records:
        print(f"  {record['text']} orientation={record['orientation']} center={record['location_center']} normalized={record['normalized_center']} box={record['book_box']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", type=Path, help="still image path")
    parser.add_argument("--camera", type=int, help="capture one frame from this camera")
    parser.add_argument("--target", help="book title; prompts when omitted")
    parser.add_argument("--output", type=Path, default=Path("offline_results/hybrid"))
    parser.add_argument("--threshold", type=float, default=0.58)
    parser.add_argument("--no-labels", action="store_true", help="save boxes without text labels; suitable for Linux without CJK fonts")
    args = parser.parse_args()
    if args.image is not None and args.camera is not None:
        parser.error("use either an image path or --camera, not both")
    if args.image is None and args.camera is None:
        parser.error("provide an image path or --camera CAMERA_INDEX")

    target = args.target or input("请输入要查找的书名: ").strip()
    if not target:
        parser.error("target title cannot be empty")

    image_path = args.image
    if args.camera is not None:
        args.output.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(args.camera)
        if not cap.isOpened():
            raise SystemExit(f"Cannot open camera index {args.camera}")
        # Discard a few startup frames so exposure and white balance can settle.
        frame = None
        for _ in range(8):
            ok, candidate = cap.read()
            if ok:
                frame = candidate
        cap.release()
        if frame is None:
            raise SystemExit("Camera opened but no frame was captured")
        stamp = time.strftime("%Y%m%d_%H%M%S")
        image_path = args.output / f"camera_{stamp}.jpg"
        cv2.imwrite(str(image_path), frame)
        print(f"Captured: {image_path}")

    locate(image_path, target, args.output, args.threshold, draw_labels=not args.no_labels)


if __name__ == "__main__":
    main()
