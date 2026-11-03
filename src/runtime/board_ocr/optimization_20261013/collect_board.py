"""Collect existing ARM evidence, without restarting any benchmark."""
import base64
import hashlib
import io
from pathlib import Path
import zipfile

print('POSTURE_REMOTE_BEGIN', flush=True)
root = Path('/home/xilinx/book_ocr_validation/results/optimization_20261013')
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix in ('.json', '.jsonl', '.log'):
            archive.writestr(path.relative_to(root).as_posix(), path.read_bytes())
data = buffer.getvalue()
print('REMOTE_ARTIFACT_BASE64 ' + base64.b64encode(data).decode(), flush=True)
print('REMOTE_ARTIFACT_SHA256 ' + hashlib.sha256(data).hexdigest(), flush=True)
print('POSTURE_REMOTE_END', flush=True)
