"""Document OCR on actual raster pages; no PDF text extraction or label input."""
import json,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    import onnxruntime as ort
    ort.preload_dlls(directory='')
    from rapidocr_onnxruntime import RapidOCR
    engine=RapidOCR(det_use_cuda=True,cls_use_cuda=True,rec_use_cuda=True,
        rec_model_path=str(ROOT/'board_ocr/models/ch_PP-OCRv5_rec_server.onnx'),
        det_limit_side_len=1280,det_limit_type='max',rec_batch_num=4,
        intra_op_num_threads=2,inter_op_num_threads=1)
    sessions=[engine.text_det.infer.session,engine.text_cls.infer.session,engine.text_rec.session.session]
    providers=[s.get_providers() for s in sessions]
    if any(p[0]!='CUDAExecutionProvider' for p in providers):raise RuntimeError('GPU OCR required; CPU fallback refused')
    out=ROOT/'output/paper-classification';manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    (out/'ocr').mkdir(exist_ok=True)
    for item in manifest:
        dest=out/'ocr'/(item['case_id']+'.json')
        if dest.exists():continue
        started=time.perf_counter();rows,_=engine(item['image']);rows=rows or []
        result=dict(case_id=item['case_id'],image=item['image'],text='\n'.join(row[1] for row in rows),
                    regions=[dict(box=row[0],text=row[1],score=float(row[2])) for row in rows],
                    ocr_seconds=round(time.perf_counter()-started,3),providers=providers)
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('OCR_DONE',item['case_id'],'regions',len(rows),'seconds',result['ocr_seconds'],flush=True)
if __name__=='__main__':main()
