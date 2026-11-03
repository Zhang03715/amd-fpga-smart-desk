"""Validate tracked names, source hashes and excluded submission material."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
paths = [path for path in paths if path]
for path in paths:
    for name in Path(path).parts:
        if name == 'README.md':
            continue
        if not re.fullmatch(r'[a-z0-9_.-]+', name):
            raise ValueError('Invalid submitted name: ' + path)
    if path.startswith(('report/', 'build/worktree/', 'config/', 'captures/')):
        raise ValueError('Excluded directory: ' + path)
    if Path(path).suffix.lower() in {'.docx', '.pdf', '.sqlite3', '.log', '.mp4', '.p12', '.pem'}:
        raise ValueError('Excluded artifact: ' + path)
for entry in json.loads((ROOT / 'build/source_map.json').read_text(encoding='utf-8')):
    content = (ROOT / entry['stored']).read_bytes()
    if hashlib.sha256(content).hexdigest() != entry['sha256']:
        raise ValueError('Source digest mismatch: ' + entry['stored'])
print('SUBMISSION_CHECK_PASS:', len(paths), 'tracked files; source hashes verified')
