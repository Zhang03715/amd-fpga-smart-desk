"""Finish the interrupted upload and start only a never-started board job."""
from pathlib import Path
import shutil
import subprocess
import sys

print('POSTURE_REMOTE_BEGIN', flush=True)
base = Path('/home/xilinx/book_ocr_validation')
destination = base / 'optimization_20261013'
out = base / 'results/optimization_20261013'
assert destination.is_dir(), 'Existing extracted experiment is required'
assert not out.exists(), 'Inspect existing output and process; never duplicate an experiment'
job = destination / 'project/board_ocr/optimization_20261013/board_job.py'
shutil.copyfile(base / 'incoming/board_job.py', job)
with (destination / 'job.log').open('w') as log:
    process = subprocess.Popen([sys.executable, str(job)], cwd=destination / 'project',
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
print('OCR_ARM_JOB_PID', process.pid, flush=True)
print('POSTURE_REMOTE_END', flush=True)
