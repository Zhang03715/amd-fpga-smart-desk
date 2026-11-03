"""Download the official versioned MediaPipe Lite bundle and provenance."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / 'models' / 'posture'
URL = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task'


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    assets = {
        'pose_landmarker_lite.task': URL,
        'MEDIAPIPE_LICENSE.txt': 'https://raw.githubusercontent.com/google-ai-edge/mediapipe/master/LICENSE',
        'model_card.pdf': 'https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf',
    }
    manifest = {}
    for name, url in assets.items():
        data = urllib.request.urlopen(url, timeout=60).read()
        (ROOT / name).write_bytes(data)
        manifest[name] = {'url': url, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
