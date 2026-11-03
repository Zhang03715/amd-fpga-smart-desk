"""Isolated serial GPU worker. Cache model sessions, never image/results."""
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace


def main():
    models={}
    configuration=None
    for line in sys.stdin:
        request=json.loads(line)
        output=Path(request['output'])
        try:
            option_bytes=Path(request['options']).read_bytes()
            settings=json.loads(option_bytes.decode('utf-8-sig'))
            weights=[Path(request['v4_model']),Path(request['v4_model']).with_name('ch_PP-OCRv4_det_infer.onnx')]
            weights.extend(Path(v) for k,v in settings.items() if k.endswith(('_model_path','_keys_path')))
            identities=tuple((str(p.resolve()),p.stat().st_size,p.stat().st_mtime_ns) for p in weights)
            signature=(request['options'],option_bytes,identities)
            if configuration is not None and signature!=configuration:
                raise ValueError('resident_configuration_changed_restart_required')
            configuration=signature
            cold=not models
            output.mkdir(parents=True,exist_ok=False)
            started=time.perf_counter()
            args=SimpleNamespace(image=Path(request['image']),output=output,
                options=Path(request['options']),v4_model=Path(request['v4_model']),
                query_title=request.get('query_title'),target=request['target'],all_texts=request['all_texts'],device='cuda',shelf_roi=request.get('shelf_roi'))
            with (output.parent/'pipeline.log').open('w',encoding='utf-8') as log:
                with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
                    from board_ocr.optimization_20261013.run_optimized_lookup import worker
                    for stage in ('scan','review','geometry'):
                        args.stage=stage
                        worker(args,models=models)
            records=[json.loads((output/(s+'.json')).read_text(encoding='utf-8')) for s in ('scan','review','geometry')]
            report=dict(target=args.target,total_wall_seconds=time.perf_counter()-started,
                all_texts=args.all_texts,device='cuda',resident_models=True,cold_start=cold,
                max_worker_peak_mib=max(r['peak_rss_mib'] for r in records),
                candidate_count=len(records[0]['candidates']),accepted_count=records[2]['accepted_count'],
                image_sha256=hashlib.sha256(args.image.read_bytes()).hexdigest(),
                v4_model_sha256=hashlib.sha256(args.v4_model.read_bytes()).hexdigest(),
                scope='Same optimized stages; resident CUDA sessions; every request rescans its image; no LEDs')
            (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            reply=dict(ok=True,output=str(output))
        except Exception as exc:
            (output.parent/'resident-error.log').write_text(traceback.format_exc(),encoding='utf-8')
            reply=dict(ok=False,error=type(exc).__name__,output=str(output))
            # Do not retain sessions after a partially failed CUDA operation.
            print(json.dumps(reply),flush=True)
            return
        print(json.dumps(reply),flush=True)


if __name__=='__main__': main()
