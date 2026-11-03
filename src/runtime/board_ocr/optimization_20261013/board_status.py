"""Read an existing job; never start or stop it."""
import json
import os
from pathlib import Path

print('POSTURE_REMOTE_BEGIN', flush=True)
root = Path('/home/xilinx/book_ocr_validation/results/optimization_20261013')
path = root / 'status.json'
if path.exists():
    state = json.loads(path.read_text())
    try:
        os.kill(state['pid'], 0)
        alive = True
    except ProcessLookupError:
        alive = False
    print(json.dumps(dict(state=state, process_exists=alive)), flush=True)
    for item in state['stages']:
        log = root / (item['stage'] + '.log')
        if log.exists():
            print(item['stage'], log.read_text()[-1600:], flush=True)
    for name in ('geometry/comparison.json', 'full/comparison.json'):
        result = root / name
        if result.exists():
            print(name, result.read_text(), flush=True)
    for log in sorted((root / 'full').rglob('parent.log')):
        print(str(log.relative_to(root)), log.read_text()[-2200:], flush=True)
    observations = root / 'memory.jsonl'
    if observations.exists():
        lines = observations.read_text().splitlines()
        if lines:
            print('latest_memory', lines[-1], flush=True)
else:
    print('Job status missing', flush=True)
print('POSTURE_REMOTE_END', flush=True)
