from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
print('POSTURE_REMOTE_BEGIN', flush=True)
base=Path('/home/xilinx/book_ocr_validation')
archive=base/'incoming/board-ocr-optimization-ready.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='8ec19908248df42a720b49255dba00b23c5f641e2b808620575783f1d1d065a3'
destination=base/'optimization_20261013'
assert not destination.exists(), 'Inspect existing experiment before launching again'
destination.mkdir()
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    for member in bundle.infolist():
        path=(destination/member.filename).resolve()
        assert destination.resolve() in path.parents
    bundle.extractall(destination)
manifest=json.loads((destination/'bundle_manifest.json').read_text())
for item in manifest['files']:
    assert hashlib.sha256((destination/'project'/item['path']).read_bytes()).hexdigest()==item['sha256']
job=destination/'project/board_ocr/optimization_20261013/board_job.py'
shutil.copyfile(base/'incoming/board_job.py',job)
with (destination/'job.log').open('w') as log:
    process=subprocess.Popen([sys.executable,str(job)],cwd=destination/'project',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
print('OCR_ARM_JOB_PID',process.pid,flush=True)
print('POSTURE_REMOTE_END',flush=True)
