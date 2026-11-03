"""Realtime, target-free bookshelf OCR and spine localisation.

Controls:
  Q / Esc  quit
  S        save the latest analysed frame and JSON
  Space    request an immediate OCR refresh
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from rapidocr_onnxruntime import RapidOCR

from hybrid_book_locator import get_font, locate_spine
from offline_book_ocr import normalise
from offline_book_segmenter import persistent_boundary_score, select_peaks


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--interval", type=float, default=1.2, help="minimum seconds between OCR jobs")
    parser.add_argument("--confidence", type=float, default=0.72)
    parser.add_argument("--max-candidates", type=int, default=18)
    parser.add_argument("--output", type=Path, default=Path("offline_results/realtime"))
    return parser.parse_args()


def polygon_bounds(points):
    pts = np.asarray(points, dtype=np.float32)
    return (
        float(pts[:, 0].min()), float(pts[:, 1].min()),
        float(pts[:, 0].max()), float(pts[:, 1].max()),
    )


def title_likelihood(points, text: str, confidence: float, width: int, height: int):
    cleaned = normalise(text)
    metadata_words = (
        "出版社", "press", "学院", "教研室", "编写组", "杂志社",
        "学年度", "总第", "主编", "编著", "责任编辑",
    )
    if (
        confidence < 0.72
        or len(cleaned) < 2
        or any(word in cleaned for word in metadata_words)
        or cleaned.endswith("编")
    ):
        return 0.0
    x1, y1, x2, y2 = polygon_bounds(points)
    bw, bh = x2 - x1, y2 - y1
    upright = bh >= bw * 1.15 and bh >= height * 0.075 and bw >= width * 0.012
    flat = bw >= bh * 1.15 and bw >= width * 0.10 and bh >= height * 0.018
    if not (upright or flat):
        return 0.0
    long_side = max(bw / width, bh / height)
    return float(confidence) * (1.0 + min(0.8, long_side)) * min(1.4, len(cleaned) / 5)


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = max(1, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter)
    return inter / union


def analyse(engine: RapidOCR, frame: np.ndarray, confidence: float, max_candidates: int):
    h, w = frame.shape[:2]
    result, _ = engine(frame)
    ranked = []
    for points, text, conf in result or []:
        score = title_likelihood(points, text, float(conf), w, h)
        if score > 0 and conf >= confidence:
            ranked.append((score, points, text, float(conf)))
    ranked.sort(key=lambda item: item[0], reverse=True)
    ranked = ranked[:max_candidates]

    boundary_score, _ = persistent_boundary_score(frame)
    upright_peaks = select_peaks(boundary_score, w)
    records = []
    for _, points, text, conf in ranked:
        box, center, orientation = locate_spine(frame, points, upright_peaks)
        record = {
            "text": text,
            "confidence": round(conf, 4),
            "orientation": orientation,
            "title_box": np.asarray(points, dtype=int).tolist(),
            "book_box": box,
            "center": center,
            "normalized_center": [round(center[0] / w, 4), round(center[1] / h, 4)],
        }
        # Several OCR fragments on one spine should produce one displayed box.
        duplicate = next((old for old in records if iou(old["book_box"], box) > 0.72), None)
        if duplicate is None:
            records.append(record)
        elif len(normalise(text)) > len(normalise(duplicate["text"])):
            records[records.index(duplicate)] = record

    canvas = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(canvas)
    font = get_font(max(18, w // 55))
    for index, record in enumerate(records, 1):
        bx1, by1, bx2, by2 = record["book_box"]
        pts = [tuple(p) for p in record["title_box"]]
        draw.rectangle((bx1, by1, bx2, by2), outline=(20, 255, 30), width=4)
        draw.line(pts + [pts[0]], fill=(255, 50, 30), width=3)
        label = f"{index} {record['text']}"
        draw.text((bx1, max(0, by1 - font.size - 3)), label, font=font,
                  fill=(20, 255, 30), stroke_width=2, stroke_fill=(0, 0, 0))
    annotated = cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)
    return annotated, records


def main():
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open camera index {args.camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    engine = RapidOCR()
    executor = ThreadPoolExecutor(max_workers=1)
    pending: Future | None = None
    latest_frame = None
    latest_annotated = None
    latest_records = []
    last_submit = 0.0
    force_refresh = True
    fps, frames, tick = 0.0, 0, time.perf_counter()
    window = "Realtime Book Locator - Q quit, S save, Space refresh"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            frames += 1
            now = time.perf_counter()
            if now - tick >= 0.5:
                fps, frames, tick = frames / (now - tick), 0, now

            if pending is not None and pending.done():
                try:
                    latest_annotated, latest_records = pending.result()
                    latest_frame = analysed_source
                    print("Detected:", ", ".join(r["text"] for r in latest_records) or "none")
                except Exception as exc:
                    print(f"OCR error: {exc}")
                pending = None

            if pending is None and (force_refresh or now - last_submit >= args.interval):
                analysed_source = frame.copy()
                pending = executor.submit(
                    analyse, engine, analysed_source, args.confidence, args.max_candidates
                )
                last_submit = now
                force_refresh = False

            display = latest_annotated.copy() if latest_annotated is not None else frame.copy()
            status = "OCR running..." if pending is not None else "OCR ready"
            cv2.putText(display, f"{status}  books={len(latest_records)}  camera_fps={fps:.1f}",
                        (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 230, 255), 2)
            cv2.imshow(window, display)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                force_refresh = True
            elif key == ord("s") and latest_annotated is not None:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                image_path = args.output / f"{stamp}_realtime.jpg"
                json_path = args.output / f"{stamp}_realtime.json"
                cv2.imwrite(str(image_path), latest_annotated)
                json_path.write_text(json.dumps(latest_records, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Saved: {image_path}")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
