"""Locate book-title text in still shelf images with RapidOCR (CPU/ONNX)."""

from __future__ import annotations

import argparse
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr_onnxruntime import RapidOCR


def normalise(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text).lower()


def similarity(target: str, text: str) -> float:
    a, b = normalise(target), normalise(text)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b)) * 0.35 + 0.65
    return SequenceMatcher(None, a, b).ratio()


def get_font(size: int):
    for path in (
        os.environ.get("BOOK_OCR_FONT", ""),
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ):
        if path and Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def process(engine: RapidOCR, path: Path, output: Path, target: str):
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"Cannot read {path}")
    result, _ = engine(image)
    records = []
    for item in result or []:
        points, text, confidence = item
        pts = np.asarray(points, dtype=np.int32)
        score = similarity(target, text) if target else 0.0
        records.append(
            {
                "text": text,
                "confidence": round(float(confidence), 4),
                "target_score": round(score, 4),
                "box": pts.tolist(),
                "center": [round(float(pts[:, 0].mean()), 1), round(float(pts[:, 1].mean()), 1)],
            }
        )

    best = max((r["target_score"] for r in records), default=0.0)
    canvas = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(canvas)
    font = get_font(max(18, image.shape[1] // 55))
    for index, record in enumerate(records, 1):
        pts = [tuple(p) for p in record["box"]]
        matched = bool(target and record["target_score"] >= max(0.58, best - 0.05))
        colour = (255, 40, 30) if matched else (20, 160, 255)
        draw.line(pts + [pts[0]], fill=colour, width=5 if matched else 2)
        x, y = pts[0]
        label = f"{index} {record['text']}"
        draw.text((x, max(0, y - font.size - 2)), label, font=font, fill=colour, stroke_width=2, stroke_fill=(0, 0, 0))

    output.mkdir(parents=True, exist_ok=True)
    overlay_path = output / f"{path.stem}_ocr.jpg"
    json_path = output / f"{path.stem}_ocr.json"
    canvas.save(overlay_path, quality=94)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{path.name}: {len(records)} text boxes -> {overlay_path}")
    if target and records:
        winner = max(records, key=lambda r: r["target_score"])
        print(f"  best target match: {winner['text']} score={winner['target_score']:.2f} center={winner['center']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--target", default="")
    parser.add_argument("--output", type=Path, default=Path("offline_results"))
    args = parser.parse_args()
    engine = RapidOCR()
    for path in args.images:
        process(engine, path, args.output, args.target)


if __name__ == "__main__":
    main()
