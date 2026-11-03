"""Explicit offline-image adapter; no camera, shelf calibration or LED driver."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def find_book(title: str, image_path: str | Path, *, threshold: float = 0.58,
              timeout_seconds: float = 90) -> dict:
    """Return evidence from this image only; raise ValueError on execution failure.

    A successful scan with found=False is not a hardware failure. File mtime is
    deliberately not interpreted as capture time or evidence of a current shelf.
    Run this blocking function in a worker when serving live UART traffic.
    """
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError("invalid_book_title")
    if not isinstance(image_path, (str, Path)) or not str(image_path).strip():
        raise ValueError("image_path_required")
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 0 < threshold <= 1):
        raise ValueError("invalid_match_threshold")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ValueError("invalid_timeout")
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("image_not_found")
    # Isolate legacy locate()'s printed output/SystemExit and bound total runtime.
    worker = """
import sys
from pathlib import Path
from hybrid_book_locator import locate
try:
    locate(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), float(sys.argv[4]))
except SystemExit as exc:
    if str(exc).startswith('No OCR match for '):
        sys.exit(3)
    raise
"""
    with tempfile.TemporaryDirectory(prefix="amd-book-find-") as output:
        try:
            completed = subprocess.run(
                [sys.executable, "-c", worker, str(path), title.strip(), output, str(threshold)],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("book_scan_timeout") from exc
        except OSError as exc:
            raise ValueError("book_worker_unavailable") from exc
        if completed.returncode == 3:
            records = []
        elif completed.returncode == 0:
            try:
                records = json.loads((Path(output) / f"{path.stem}_hybrid.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("book_result_invalid") from exc
        else:
            raise ValueError("book_scan_failed")
    return {
        "title": title.strip(), "found": bool(records), "matches": records,
        "source": {"kind": "offline_image", "path": str(path),
                   "capture_time": None, "freshness": "unknown", "live": False},
        "indicator_lit": False, "shelf_slot": None,
        "message": "仅为所给图片的识别结果；未确认当前书架位置，未点亮指示灯。",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    try:
        result = find_book(args.title, args.image, timeout_seconds=args.timeout)
    except ValueError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        raise SystemExit(1)
    print(json.dumps({"status": "success", "data": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
