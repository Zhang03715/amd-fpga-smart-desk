"""Reuse the verified opt-in OCR pipeline; never request CPU fallback."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def grouped_preview(image_path, spines, regions, destination):
    from PIL import Image, ImageDraw, ImageFont
    with Image.open(image_path) as original:
        canvas = original.convert('RGB')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=max(18,canvas.width//60))
    for region in regions:
        points = [tuple(map(int, p)) for p in region['title_box']]
        draw.line(points+[points[0]], fill=(255,40,30), width=3)
    for index, spine in enumerate(spines,1):
        quality=spine.get('geometry_quality',{})
        color=(255,180,0) if quality.get('status')=='review_required' else (20,255,30)
        polygon = spine.get('spine_polygon')
        if polygon:
            corners = [tuple(map(int,p)) for p in polygon]
            draw.line(corners+[corners[0]],fill=color,width=6)
        else:
            draw.rectangle(spine['book_box'],outline=color,width=6)
        x,y = spine['book_box'][:2]
        label=f'S{index}'+('?' if quality.get('status')=='review_required' else '')
        draw.text((x+8,y+4),label,font=font,fill=color,stroke_width=2,stroke_fill=(0,0,0))
    canvas.save(destination,quality=95)


class GPUPipeline:
    def __init__(self, python, options, v4_model, timeout=180, upright_geometry=False, resident_models=False):
        self.python, self.options, self.v4_model = map(Path, (python, options, v4_model))
        self.timeout = timeout
        self.upright_geometry = bool(upright_geometry)
        self.resident = None
        if resident_models:
            from .resident import ResidentRunner
            self.resident=ResidentRunner(python,ROOT)
        if not math.isfinite(timeout) or not 0 < timeout <= 600:
            raise ValueError('timeout must be finite and within 1..600 seconds')
        for path in (self.python, self.options, self.v4_model):
            if not path.is_file():
                raise ValueError('missing local runtime/model configuration: ' + str(path))

    def __call__(self, image_path, request, output_dir):
        output_dir = Path(output_dir)
        if request['action']=='paper.classify' and request['params'].get('operation')=='wrong_question':
            target=output_dir/'wrong-extraction'
            completed=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'question_extraction/run.py'),str(image_path.resolve()),'--output',str(target.resolve()),'--export-desktop'],cwd=ROOT,capture_output=True,timeout=160)
            if completed.returncode:raise ValueError('wrong_question_extraction_failed')
            result=json.loads((target/'result.json').read_text(encoding='utf-8'))
            return dict(sheet_id=request['request_id'],operation='wrong_question',saved_count=sum(bool(q.get('marked')) for q in result.get('questions',[])),desktop_folder=result.get('desktop_export'),review_required=True,motor_action=False)
        if request['action']=='paper.classify':
            import urllib.request,base64
            payload=json.dumps(dict(sheet_id=request['request_id'],image_base64=base64.b64encode(image_path.read_bytes()).decode('ascii'))).encode()
            call=urllib.request.Request('http://127.0.0.1:8770/classify',payload,{'Content-Type':'application/json'})
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(call,timeout=min(160,self.timeout)) as response:result=json.load(response)
            if result.get('sheet_id')!=request['request_id']:raise ValueError('paper_result_identity_mismatch')
            return dict(result,action='paper.classify',inference_location='local_pc_gpu',motor_action=False)
        work = output_dir / 'pipeline'
        if self.resident is None: work.mkdir()
        command = [str(self.python), str(ROOT/'board_ocr/optimization_20261013/run_optimized_lookup.py'),
                   str(image_path), '--target', request['params'].get('title', 'BLIND_EVALUATION'),
                   '--options', str(self.options), '--v4-model', str(self.v4_model),
                   '--output', str(work), '--device', 'cuda']
        if request['action'] == 'book.scan':
            command.append('--all-texts')
        if request['params'].get('shelf_roi') is not None:
            command+=['--shelf-roi']+[str(v) for v in request['params']['shelf_roi']]
        if request['params'].get('query_title'):
            command+=['--query-title',request['params']['query_title']]
        started = time.monotonic()
        if self.resident is not None:
            self.resident.run(dict(image=str(image_path.resolve()),output=str(work.resolve()),
                target=request['params'].get('title','BLIND_EVALUATION'),
                all_texts=request['action']=='book.scan',query_title=request['params'].get('query_title'),options=str(self.options.resolve()),
                v4_model=str(self.v4_model.resolve()),shelf_roi=request['params'].get('shelf_roi')),self.timeout)
        else:
            self._run_subprocess(command,output_dir)
        return self._collect(image_path,request,output_dir,work,started)

    def _run_subprocess(self,command,output_dir):
        with (output_dir/'pipeline.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=os.name != 'nt')
            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise TimeoutError('GPU pipeline timeout')
        if process.returncode:
            raise RuntimeError('GPU pipeline failed; see local pipeline/stage logs')

    def close(self):
        if self.resident is not None:self.resident.close()

    def _collect(self,image_path,request,output_dir,work,started):
        read = lambda name: json.loads((work/name).read_text(encoding='utf-8'))
        summary, scan, review = read('summary.json'), read('scan.json'), read('review.json')
        if summary['device'] != 'cuda' or any(providers[0] != 'CUDAExecutionProvider' for providers in scan['provider_audit'].values()) or review['providers'][0] != 'CUDAExecutionProvider':
            raise RuntimeError('CUDA provider audit failed')
        records = read(image_path.stem+'_hybrid.json')
        import cv2
        from spine_groups import group_spine_regions
        grouping_started = time.monotonic()
        image = cv2.imread(str(image_path))
        geometry_records = records
        if self.upright_geometry:
            from upright_geometry import refine_upright_records
            geometry_records = refine_upright_records(image,records)
            (output_dir/'upright_geometry.json').write_text(
                json.dumps(geometry_records,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        grouped = group_spine_regions(image, geometry_records, crosswise_cleanup=self.upright_geometry)
        if self.upright_geometry:
            from spine_geometry_quality import annotate_geometry_quality
            grouped=annotate_geometry_quality(grouped)
        (output_dir/'spine_groups.json').write_text(json.dumps(grouped,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        grouped_preview(image_path,grouped['spines'],grouped['regions'],output_dir/'preview.jpg')
        return dict(action=request['action'], found=bool(records), matches=records,
                    image_size=[int(image.shape[1]),int(image.shape[0])],
                    count_semantics='accepted_text_regions_with_spine_geometry_not_unique_books',
                    text_regions=grouped['regions'],spines=grouped['spines'],
                    spine_count=len(grouped['spines']),spine_count_semantics='OCR_anchored_spine_hypotheses',
                    grouping_audit=grouped['audit'],grouping_and_preview_seconds=time.monotonic()-grouping_started,
                    geometry_mode='upright_experimental' if self.upright_geometry else 'legacy',
                    geometry_quality_evaluated=self.upright_geometry,
                    geometry_review_required_count=(sum(
                        spine.get('geometry_quality',{}).get('status')=='review_required'
                        for spine in grouped['spines']) if self.upright_geometry else None),
                    decisions=review['decisions'], summary=summary,
                    provider_audit=scan['provider_audit'], review_providers=review['providers'],
                    inference_location='local_pc_gpu', indicator_lit=False, motor_action=False,
                    pipeline_seconds=time.monotonic()-started)
