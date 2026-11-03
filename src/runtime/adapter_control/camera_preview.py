"""Latest-frame camera worker isolated from the LCD/MMIO owner process."""
import io
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
from PIL import Image

HEADER = struct.Struct('<dQ')


def decode_packet(payload, now, max_age=2.0):
    if len(payload) <= HEADER.size or len(payload) > 2_000_000:
        raise ValueError('Invalid camera packet size')
    captured, sequence = HEADER.unpack_from(payload)
    age = now-captured
    if not 0 <= age <= max_age:
        raise ValueError('Stale camera frame')
    with Image.open(io.BytesIO(payload[HEADER.size:])) as image:
        if image.size != (320, 240):
            raise ValueError('Unexpected preview dimensions')
        return image.convert('RGB'), sequence, age


class LatestCamera:
    def __init__(self, device):
        self.folder = tempfile.TemporaryDirectory(prefix='amd-preview-',
            dir='/dev/shm' if Path('/dev/shm').is_dir() else None)
        self.path = Path(self.folder.name)/'latest.bin'
        self.process = subprocess.Popen([sys.executable, '-m', __name__,
            '--worker', str(device), str(self.path)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def latest(self):
        if self.process.poll() is not None:
            raise RuntimeError('Camera worker stopped')
        return decode_packet(self.path.read_bytes(), time.monotonic())

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.folder.cleanup()


def worker(device, path):
    import cv2
    # Leave the second ARM core available to the NCNN worker instead of making
    # capture conversion/resizing compete through another OpenCV thread pool.
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError('Camera open failed')
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    sequence = 0
    path = Path(path)
    temporary = path.with_suffix('.part')
    try:
        while True:
            ok, frame = cap.read()
            captured = time.monotonic()
            if not ok:
                raise RuntimeError('Camera read failed')
            height, width = frame.shape[:2]
            if sequence == 0:
                import json
                path.with_name('camera-info.json').write_text(json.dumps(dict(
                    device=device,width=width,height=height,
                    reported_fps=cap.get(cv2.CAP_PROP_FPS),opencv_threads=cv2.getNumThreads())))
            scale = min(320/width, 240/height)
            frame = cv2.resize(frame, (max(1, round(width*scale)), max(1, round(height*scale))))
            bottom = 240-frame.shape[0]
            right = 320-frame.shape[1]
            frame = cv2.copyMakeBorder(frame, bottom//2, bottom-bottom//2,
                right//2, right-right//2, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                raise RuntimeError('Camera encode failed')
            sequence += 1
            temporary.write_bytes(HEADER.pack(captured, sequence)+encoded.tobytes())
            os.replace(temporary, path)
    finally:
        cap.release()


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--worker':
        raise SystemExit('Internal camera worker invocation required')
    worker(int(sys.argv[2]), sys.argv[3])
