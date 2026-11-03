"""Serial-launched, isolated real ARM experiment; no sudo or hardware IO."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('/home/xilinx/book_ocr_validation')
OUT = BASE/'results/optimization_20261013'


def memory():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, rest = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            values[key] = int(rest.strip().split()[0])
    values['SwapUsed'] = values['SwapTotal']-values['SwapFree']
    return values


def save(state):
    temporary = OUT/'status.tmp'
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(OUT/'status.json')


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    state = dict(pid=os.getpid(), started=time.time(), architecture=os.uname().machine,
                 baseline_memory_kib=memory(), stages=[], running=True)
    save(state)
    here = ROOT/'board_ocr/optimization_20261013'
    cases = json.loads((here/'geometry_cases.json').read_text())
    manifest = OUT/'geometry_d.json'
    manifest.write_text(json.dumps([case for case in cases if case['name']=='d']))
    environment = dict(os.environ, PYTHONPATH=str(BASE/'runtime'), OMP_NUM_THREADS='2',
                       PYTHONIOENCODING='utf-8')
    jobs = [
        ('tests', [sys.executable, '-m', 'unittest',
                   'board_ocr.optimization_20261013.test_geometry_cache',
                   'board_ocr.optimization_20261013.test_reuse', 'test_spine_geometry',
                   'test_verification_policy', 'test_expanded_title_review', 'test_flat_spine_extent', '-v']),
        ('geometry', [sys.executable, str(here/'benchmark_geometry.py'), '--manifest', str(manifest),
                      '--output', str(OUT/'geometry'), '--repeat', '1']),
        ('full', [sys.executable, str(here/'benchmark_lookup.py'), '--options', str(here/'options_board.json'),
                  '--v4-model', str(BASE/'runtime/rapidocr_onnxruntime/models/ch_PP-OCRv4_rec_infer.onnx'),
                  '--output', str(OUT/'full'), '--device', 'cpu', '--case', 'd', '--repeat', '1'])]
    with (OUT/'memory.jsonl').open('w') as observations:
        for name, command in jobs:
            with (OUT/f'{name}.log').open('w') as log:
                process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                           stdout=log, stderr=subprocess.STDOUT)
                item = dict(stage=name, pid=process.pid, started=time.time(), running=True)
                state['stages'].append(item)
                save(state)
                while process.poll() is None:
                    observations.write(json.dumps(dict(time=time.time(), stage=name, **memory()))+'\n')
                    observations.flush()
                    time.sleep(.5)
                item.update(running=False, returncode=process.returncode, ended=time.time())
                save(state)
                if process.returncode != 0:
                    break
    state.update(running=False, ended=time.time(), final_memory_kib=memory())
    save(state)
    print(json.dumps(state), flush=True)


if __name__ == '__main__':
    main()
