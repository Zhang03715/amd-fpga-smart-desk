import sys,json
from pathlib import Path
from PIL import Image
import onnxruntime as ort
ort.preload_dlls(directory='')
from rapidocr_onnxruntime import RapidOCR
root=Path(__file__).resolve().parents[1]
with Image.open(sys.argv[1]) as im:
 if im.width*im.height>24000000:raise ValueError('image_dimensions')
 im.verify()
e=RapidOCR(det_use_cuda=True,cls_use_cuda=True,rec_use_cuda=True,rec_model_path=str(root/'board_ocr/models/ch_PP-OCRv5_rec_server.onnx'),det_limit_side_len=1280,rec_batch_num=4,intra_op_num_threads=2,inter_op_num_threads=1)
assert all(s.get_providers()[0]=='CUDAExecutionProvider' for s in [e.text_det.infer.session,e.text_cls.infer.session,e.text_rec.session.session])
rows,_=e(sys.argv[1]);Path(sys.argv[2]).write_text(json.dumps({'text':'\n'.join(r[1] for r in rows or []),'regions':[{'box':r[0],'text':r[1],'score':float(r[2])} for r in rows or []]},ensure_ascii=False),encoding='utf-8')
