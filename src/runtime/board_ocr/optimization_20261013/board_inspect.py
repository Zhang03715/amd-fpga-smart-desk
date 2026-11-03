from pathlib import Path
import json
import os
print('POSTURE_REMOTE_BEGIN', flush=True)
root=Path('/home/xilinx/book_ocr_validation')
items={}
for name in ('project/tools/run_verified_lookup.py','runtime/rapidocr_onnxruntime/models/ch_PP-OCRv4_rec_infer.onnx',
             'paddle_lite_trial/v6_tiny/inference.onnx','paddle_lite_trial/v6_tiny/ppocrv6_tiny_dict.txt',
             'project/captures/new_flat_20261008/shelf_flat_d.jpg'):
    path=root/name
    items[name]=dict(exists=path.exists(),bytes=path.stat().st_size if path.exists() else None)
print(json.dumps(dict(machine=os.uname().machine, files=items),indent=2),flush=True)
print(Path('/proc/meminfo').read_text(),flush=True)
print('POSTURE_REMOTE_END',flush=True)
