"""Opt-in derivative: exact crop reuse, strict expansion pruning, request-local geometry reuse. Models remain in separate processes for ARM memory limits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def memory():
    if sys.platform == 'win32':
        from tools.benchmark_static_ocr import peak_memory_mib
        return peak_memory_mib()
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024


def worker(args, models=None):
    import cv2
    from verification_policy import needs_review, decide
    started = time.perf_counter()
    if args.device=='cuda':
        import onnxruntime as ort
        ort.preload_dlls(directory='')
        if 'CUDAExecutionProvider' not in ort.get_available_providers():
            raise RuntimeError('CUDA provider unavailable; refusing CPU fallback')
    def checked_providers(session):
        providers=session.get_providers()
        if args.device=='cuda' and providers[0]!='CUDAExecutionProvider':
            raise RuntimeError(f'CUDA requested but active providers are {providers}')
        return providers
    output = args.output
    if args.stage == 'scan':
        from rapidocr_onnxruntime import RapidOCR
        options = json.loads(args.options.read_text(encoding='utf-8-sig'))
        actual_max_side = options.pop('det_actual_max_side', None)
        expand_flat_crops = options.pop('expand_flat_crops',False)
        options.pop('flat_seam_extent',None)
        options.pop('refine_title_rois', None)
        options.pop('native_title_review', None)
        native_tiles=options.pop('native_tile_detection',False)
        rotated_titles=options.pop('rotated_title_detection',False)
        options.pop('review_batch_size',None)
        options.pop('edge_label_review',None)
        options.pop('review_rec_model_path',None)
        options.pop('review_context_margin',None)
        shelf_roi=getattr(args,'shelf_roi',None)
        options.update(det_use_cuda=args.device=='cuda',cls_use_cuda=args.device=='cuda',rec_use_cuda=args.device=='cuda')
        if models is not None and 'scan' in models:
            engine = models['scan']
        else:
            engine = RapidOCR(**options)
            if models is not None: models['scan'] = engine
        provider_audit=dict(det=checked_providers(engine.text_det.infer.session),
            cls=checked_providers(engine.text_cls.infer.session),rec=checked_providers(engine.text_rec.session.session))
        detection_audit = {}
        if actual_max_side is not None:
            from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
            if not 640 <= int(actual_max_side) <= 2000:
                raise ValueError('det_actual_max_side outside experiment range')
            detector = engine.text_det
            def get_preprocess(max_wh):
                preprocess = DetPreProcess(int(actual_max_side),'max',detector.mean,detector.std)
                def audited(image):
                    tensor = preprocess(image)
                    detection_audit.update(original_shape=list(image.shape),
                        tensor_shape=list(tensor.shape) if tensor is not None else None,
                        requested_max_side=int(actual_max_side))
                    return tensor
                return audited
            detector.get_preprocess = get_preprocess
        image = cv2.imread(str(args.image))
        if image is None:
            raise ValueError('Unreadable image')
        from board_ocr.optimization_20261013.reuse import scan_with_crops
        rows, stages, reused_crops = scan_with_crops(engine, image)
        rows = rows or []
        candidates = []
        for i, row in enumerate(rows):
            if shelf_roi:
                from board_ocr.optimization_20261013.native_tiles import bounds
                b=bounds(row[0]);x,y=(b[0]+b[2])/2,(b[1]+b[3])/2
                if not (shelf_roi[0]<=x<=shelf_roi[2] and shelf_roi[1]<=y<=shelf_roi[3]):continue
            if args.all_texts or needs_review(args.target, row[1]):
                candidates.append(dict(id=i, points=row[0], tiny_text=row[1], tiny_confidence=float(row[2])))
        crop_reuse = dict(reused_count=0, fallback_count=0)
        if candidates:
            import numpy as np
            if reused_crops is not None:
                crops = [reused_crops[c['id']] for c in candidates]
                crop_reuse = dict(reused_count=len(crops), fallback_count=0)
            else:
                crops = engine.get_crop_img_list(image, [np.asarray(c['points'],dtype=np.float32) for c in candidates])
                crops, _, _ = engine.text_cls(crops)
                crop_reuse = dict(reused_count=0, fallback_count=len(crops))
            for c, crop in zip(candidates,crops):
                c['crop_file'] = f"candidate_{c['id']:03d}.png"
                if not cv2.imwrite(str(output/c['crop_file']),crop):
                    raise RuntimeError('Could not save review crop')
            if expand_flat_crops:
                for c in candidates:
                    pts=np.asarray(c['points'],dtype=np.float32)
                    if np.ptp(pts[:,0])<=np.ptp(pts[:,1])*1.15: continue
                    axis=pts[1]-pts[0];axis/=max(1,np.linalg.norm(axis))
                    pad=np.linalg.norm(pts[3]-pts[0])*.9
                    pts[[0,3]]-=axis*pad;pts[[1,2]]+=axis*pad
                    pts[:,0]=np.clip(pts[:,0],0,image.shape[1]-1);pts[:,1]=np.clip(pts[:,1],0,image.shape[0]-1)
                    expanded=engine.get_crop_img_list(image,[pts]);expanded,_,_=engine.text_cls(expanded)
                    c['expanded_crop_file']=f"expanded_{c['id']:03d}.png";c['expanded_points']=pts.tolist()
                    if not cv2.imwrite(str(output/c['expanded_crop_file']),expanded[0]): raise RuntimeError('Expanded crop write failed')
        tile_audit={}
        if native_tiles:
            from board_ocr.optimization_20261013.native_tiles import detect
            boxes,tile_audit=detect(image,engine.text_det,[c['points'] for c in candidates],shelf_roi)
            if boxes:
                crops=engine.get_crop_img_list(image,boxes);crops,_,_=engine.text_cls(crops)
                for i,(points,crop) in enumerate(zip(boxes,crops),len(rows)):
                    name=f'tile_{i:03d}.png'
                    if not cv2.imwrite(str(output/name),crop):raise RuntimeError('tile crop write failed')
                    candidates.append(dict(id=i,points=points.tolist(),tiny_text='',tiny_confidence=0.,crop_file=name,native_tile=True))
        rotated_audit={}
        if rotated_titles:
            import numpy as np
            from rapidocr_onnxruntime.ch_ppocr_det import TextDetector
            from board_ocr.optimization_20261013.native_tiles import detect
            from board_ocr.optimization_20261013.rotated_review import restore_points
            if models is not None and 'geometry_detector' in models:rotated_detector=models['geometry_detector']
            else:
                rotated_detector=TextDetector(dict(model_path=str(args.v4_model.with_name('ch_PP-OCRv4_det_infer.onnx')),
                    limit_type='max',limit_side_len=960,mean=[.5]*3,std=[.5]*3,
                    intra_op_num_threads=2,inter_op_num_threads=1,use_cuda=args.device=='cuda',use_dml=False))
                if models is not None:models['geometry_detector']=rotated_detector
            provider_audit['rotated_det']=checked_providers(rotated_detector.infer.session)
            left,top,right,bottom=shelf_roi or [0,0,image.shape[1],image.shape[0]]
            region=image[top:bottom,left:right]
            view=cv2.rotate(region,cv2.ROTATE_90_CLOCKWISE)
            boxes,rotated_audit=detect(view,rotated_detector,[],limit=24)
            boxes=[restore_points(p,left,top,bottom-top) for p in boxes]
            upright_boxes,upright_audit=detect(region,rotated_detector,[],limit=24)
            upright_boxes=[p+np.array([left,top],np.float32) for p in upright_boxes
                           if np.ptp(p[:,1])>np.ptp(p[:,0])*1.15]
            boxes+=upright_boxes
            rotated_audit['original_upright_view']=upright_audit
            if boxes:
                crops=engine.get_crop_img_list(image,boxes)
                next_id=max((c['id'] for c in candidates),default=-1)+1
                for i,(points,crop) in enumerate(zip(boxes,crops),next_id):
                    name=f'rotated_{i:03d}.png'
                    if not cv2.imwrite(str(output/name),crop):raise RuntimeError('rotated crop write failed')
                    candidates.append(dict(id=i,points=points.tolist(),tiny_text='',tiny_confidence=0.,
                        crop_file=name,native_tile=True,rotated_view=True))
        report = dict(rotated_titles=rotated_audit,native_tiles=tile_audit,crop_reuse=crop_reuse, candidates=candidates, provider_audit=provider_audit, all_texts=args.all_texts, ocr_stage_seconds=stages, detection_audit=detection_audit,
                      work_seconds=time.perf_counter()-started, peak_rss_mib=memory())
        (output/'scan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    elif args.stage == 'review':
        from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer
        review_options=json.loads(args.options.read_text(encoding='utf-8-sig'))
        review_model=Path(review_options.get('review_rec_model_path',args.v4_model))
        config = dict(model_path=str(review_model),rec_img_shape=[3,48,320],rec_batch_num=int(review_options.get('review_batch_size',1)),
                      intra_op_num_threads=2,inter_op_num_threads=1,use_cuda=args.device=='cuda',use_dml=False)
        if models is not None and 'review' in models:
            recognizer = models['review']
        else:
            recognizer = TextRecognizer(config)
            if models is not None: models['review'] = recognizer
        providers=checked_providers(recognizer.session.session)
        secondary=None
        if review_options.get('rotated_title_detection'):
            if models is not None and 'secondary_review' in models:secondary=models['secondary_review']
            else:
                secondary=TextRecognizer(dict(config,model_path=str(args.v4_model)))
                if models is not None:models['secondary_review']=secondary
            checked_providers(secondary.session.session)
        glyph_recognizer=None;glyph_model_audit={}
        if review_options.get('glyph_rec_model_path'):
            glyph_model=Path(review_options['glyph_rec_model_path'])
            glyph_keys=Path(review_options['glyph_rec_keys_path'])
            if models is not None and 'glyph_review' in models:glyph_recognizer=models['glyph_review']
            else:
                glyph_recognizer=TextRecognizer(dict(config,model_path=str(glyph_model),rec_keys_path=str(glyph_keys)))
                if models is not None:models['glyph_review']=glyph_recognizer
            glyph_model_audit=dict(model=str(glyph_model),sha256=hashlib.sha256(glyph_model.read_bytes()).hexdigest(),
                keys_sha256=hashlib.sha256(glyph_keys.read_bytes()).hexdigest(),providers=checked_providers(glyph_recognizer.session.session))
        review_caches=[]
        if review_options.get('exact_crop_review_cache'):
            from board_ocr.optimization_20261013.recognition_cache import RecognitionCache
            recognizer=RecognitionCache(recognizer);review_caches.append(recognizer)
            if secondary is not None:
                secondary=RecognitionCache(secondary);review_caches.append(secondary)
            if glyph_recognizer is not None:
                glyph_recognizer=RecognitionCache(glyph_recognizer);review_caches.append(glyph_recognizer)
        scan = json.loads((output/'scan.json').read_text(encoding='utf8'))
        review_options=json.loads(args.options.read_text(encoding='utf-8-sig'))
        native_image=cv2.imread(str(args.image)) if review_options.get('native_title_review') else None
        native_count=0
        vertical_count=0
        decisions = []
        from expanded_title_review import use_expanded_text
        from board_ocr.optimization_20261013.reuse import expansion_can_change_selection
        primary_batches={}
        if review_options.get('review_batch_size',1)>1:
            all_images=[];ranges=[]
            for candidate in scan['candidates']:
                item=cv2.imread(str(output/candidate['crop_file']))
                images=[item,cv2.rotate(item,cv2.ROTATE_180)] if candidate.get('native_tile') else [item]
                ranges.append((candidate['id'],len(all_images),len(images)));all_images.extend(images)
            if all_images:
                rows,batch_seconds=recognizer(all_images)
                for cid,start,count in ranges:primary_batches[cid]=(rows[start:start+count],float(batch_seconds)*count/len(all_images))
        for c in scan['candidates']:
            crop = cv2.imread(str(output/c['crop_file']))
            variants=[crop,cv2.rotate(crop,cv2.ROTATE_180)] if c.get('native_tile') else [crop]
            result, seconds = primary_batches[c['id']] if c['id'] in primary_batches else recognizer(variants)
            text, confidence = max(result,key=lambda row:float(row[1]))
            extra={}
            if c.get('rotated_view'):
                from board_ocr.optimization_20261013.rotated_review import choose,needs_padding
                alternate,secondary_seconds=secondary(variants)
                other=max(alternate,key=lambda row:float(row[1]))
                padding_needed=not review_options.get('prune_unusable_fallback') or needs_padding((text,float(confidence)),other)
                if padding_needed:
                    margin=max(1,round(min(crop.shape[:2])*.03))
                    padded=cv2.copyMakeBorder(crop,margin,margin,margin,margin,cv2.BORDER_REPLICATE)
                    padded_rows,padded_seconds=secondary([padded,cv2.rotate(padded,cv2.ROTATE_180)])
                    again=max(padded_rows,key=lambda row:float(row[1]))
                else:again=other;padded_seconds=0.
                (text,confidence),audit=choose((text,float(confidence)),other,again)
                if not padding_needed:audit.update(padded_text=None,padded_confidence=None,padded_skipped='cannot_change_existing_selection')
                extra.update(rotated_review=dict(audit,seconds=float(secondary_seconds+padded_seconds)),
                             recognition_conflict=audit['conflict'])
            if c.get('rotated_view') and review_options.get('edge_label_review'):
                from board_ocr.optimization_20261013.edge_label import span,select,clipped_points
                interval=span(crop)
                if interval is not None:
                    left,right=interval;trimmed=crop[:,left:right]
                    rows,trim_seconds=recognizer([trimmed,cv2.rotate(trimmed,cv2.ROTATE_180)])
                    trimmed_text,trimmed_confidence=max(rows,key=lambda row:float(row[1]))
                    pad=max(1,round(trimmed.shape[0]*.03))
                    corroborating=cv2.copyMakeBorder(trimmed,pad,pad,pad,pad,cv2.BORDER_REPLICATE)
                    extra_rows,extra_seconds=recognizer([corroborating,cv2.rotate(corroborating,cv2.ROTATE_180)])
                    again=max(extra_rows,key=lambda row:float(row[1]))
                    selected=select(text,float(confidence),trimmed_text,float(trimmed_confidence),again)
                    name=f'edge_label_{c["id"]:03d}.png'
                    if not cv2.imwrite(str(output/name),trimmed):raise RuntimeError('edge label crop write failed')
                    extra['edge_label_review']=dict(span=interval,crop_file=name,original_text=text,
                        original_confidence=float(confidence),text=trimmed_text,confidence=float(trimmed_confidence),
                        corroborating_text=again[0],corroborating_confidence=float(again[1]),
                        selected=selected,seconds=float(trim_seconds+extra_seconds))
                    if selected:
                        c=dict(c,points=clipped_points(c['points'],left,right,crop.shape[1]))
                        text,confidence=trimmed_text,float(trimmed_confidence)
                        from verification_policy import title_key
                        if title_key(again[0])==title_key(text) and again[1]>=.90:confidence=min(confidence,float(again[1]))
                        extra['recognition_conflict']=True  # Require a second fresh frame.
            if review_options.get('review_context_margin') and .75<=float(confidence)<.95:
                from board_ocr.optimization_20261013.native_tiles import select_margin
                margin=max(1,round(min(crop.shape[:2])*.08))
                padded=cv2.copyMakeBorder(crop,margin,margin,margin,margin,cv2.BORDER_REPLICATE)
                padded_variants=[padded,cv2.rotate(padded,cv2.ROTATE_180)] if c.get('native_tile') else [padded]
                padded_rows,padded_seconds=recognizer(padded_variants)
                padded_text,padded_confidence=max(padded_rows,key=lambda row:float(row[1]))
                selected=select_margin(text,float(confidence),padded_text,float(padded_confidence))
                extra['context_margin']=dict(pixels=margin,original_text=text,original_confidence=float(confidence),
                    text=padded_text,confidence=float(padded_confidence),selected=selected,seconds=float(padded_seconds))
                if selected:text,confidence=padded_text,padded_confidence
            if c.get('expanded_crop_file') and expansion_can_change_selection(text, None if args.all_texts else args.target):
                expanded_result,expanded_seconds=recognizer([cv2.imread(str(output/c['expanded_crop_file']))])
                expanded_text,expanded_confidence=expanded_result[0]
                selected=use_expanded_text(text,expanded_text,float(expanded_confidence),None if args.all_texts else args.target)
                extra.update(dict(original_v4_text=text,original_v4_confidence=float(confidence),expanded_v4_text=expanded_text,
                    expanded_v4_confidence=float(expanded_confidence),expanded_inference_seconds=float(expanded_seconds),expanded_selected=selected))
                if selected:
                    text,confidence=expanded_text,expanded_confidence;c=dict(c,points=c['expanded_points'])
            if c.get('expanded_crop_file') and not extra:
                extra = dict(expanded_review_skipped='cannot_satisfy_existing_strict_expansion_rule')
            if native_image is not None and native_count<12 and not c.get('native_tile'):
                from verification_policy import title_key
                if float(confidence)<.95 or title_key(c['tiny_text'])!=title_key(text):
                    from rapidocr_onnxruntime.ch_ppocr_det import TextDetector
                    from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
                    detector_config=dict(model_path=str(args.v4_model.with_name('ch_PP-OCRv4_det_infer.onnx')),
                        limit_type='max',limit_side_len=960,mean=[0.5]*3,std=[0.5]*3,
                        intra_op_num_threads=2,inter_op_num_threads=1,use_cuda=args.device=='cuda',use_dml=False)
                    if models is not None and 'geometry_detector' in models:
                        native_detector=models['geometry_detector']
                    else:
                        native_detector=TextDetector(detector_config)
                        if models is not None:models['geometry_detector']=native_detector
                    checked_providers(native_detector.infer.session)
                    native_detector.get_preprocess=lambda max_wh:DetPreProcess(960,'max',native_detector.mean,native_detector.std)
                    from board_ocr.optimization_20261013.native_roi import refine
                    text,confidence,points,audit=refine(native_image,c['points'],text,float(confidence),
                        native_detector,recognizer,output,c['id'])
                    c=dict(c,points=points);extra['native_review']=audit;native_count+=1
            if review_options.get('upright_glyph_review') and native_image is not None and float(confidence)<(.95 if glyph_recognizer is not None else .90) and vertical_count<12:
                from board_ocr.optimization_20261013.vertical_text import reflow,review as review_glyphs
                prepared=reflow(native_image,c['points'])
                if prepared is not None:
                    line,audit=prepared;vertical_count+=1
                    (reviewed_text,reviewed_confidence),read_audit=review_glyphs((text,float(confidence)),line,
                        audit['character_cells'],recognizer,glyph_recognizer)
                    name=f'upright_glyph_{c["id"]:03d}.png'
                    if not cv2.imwrite(str(output/name),line):raise RuntimeError('upright glyph crop write failed')
                    extra['upright_glyph_review']=dict(audit,crop_file=name,original_text=text,
                        original_confidence=float(confidence),text=reviewed_text,confidence=float(reviewed_confidence),
                        corroborating_layout='two_pixel_cell_gap',**read_audit)
                    if read_audit['selected']:
                        text,confidence=reviewed_text,reviewed_confidence
                        extra['recognition_conflict']=True  # A second fresh frame must confirm it.
            decision = dict(accepted=float(confidence)>=.90,status='transcribed',reason='blind_all_texts_confidence_gate') if args.all_texts else decide(args.target,c['tiny_text'],text,float(confidence))
            if c.get('rotated_view'):
                from verification_policy import title_key
                if len(title_key(text))<4:decision.update(accepted=False,reason='orientation_rescue_short_text')
            d = dict(c,v4_text=text,v4_confidence=float(confidence),v4_inference_seconds=float(seconds), **extra, **decision)
            decisions.append(d)
        query_audit={}
        if getattr(args,'query_title',None) and review_options.get('query_crop_review',False):
            from board_ocr.optimization_20261013.query_rescue import rescue
            query_audit=rescue(cv2.imread(str(args.image)),decisions,args.query_title,recognizer,glyph_recognizer,output,detector=models.get('geometry_detector') if models is not None else locals().get('native_detector'))
        if review_options.get('native_tile_detection'):
            from board_ocr.optimization_20261013.native_tiles import overlap,bounds
            from verification_policy import title_key
            kept=[]
            for d in sorted((d for d in decisions if d['accepted']),key=lambda d:d['v4_confidence'],reverse=True):
                duplicate=next((k for k in kept if title_key(k['v4_text'])==title_key(d['v4_text'])
                                and overlap(bounds(k['points']),bounds(d['points']))>=.45),None)
                if duplicate is not None:d.update(accepted=False,reason='duplicate_same_text_region',duplicate_of=duplicate['id'])
                else:kept.append(d)
        conflict_audit={}
        if review_options.get('resolve_transcription_conflicts'):
            from board_ocr.optimization_20261013.transcription_conflicts import resolve
            fingerprints={}
            for d in decisions:
                name=d['crop_file']
                for key in ('native_review','edge_label_review','upright_glyph_review'):
                    if d.get(key,{}).get('selected'):name=d[key]['crop_file']
                fingerprints[d['id']]=hashlib.sha256((output/name).read_bytes()).hexdigest()
            conflict_audit=resolve(decisions,fingerprints)
        (output/'review.json').write_text(json.dumps(dict(decisions=decisions,providers=providers,review_model=str(review_model),
            transcription_conflicts=conflict_audit,
            recognition_cache=[cache.info() for cache in review_caches],
            glyph_model=glyph_model_audit,
            query_crop_review=query_audit,review_model_sha256=hashlib.sha256(review_model.read_bytes()).hexdigest(),
            work_seconds=time.perf_counter()-started,peak_rss_mib=memory()),ensure_ascii=False,indent=2),encoding='utf8')
    else:
        from hybrid_book_locator import locate
        review = json.loads((output/'review.json').read_text(encoding='utf8'))
        rows = [[d['points'],d['v4_text'],d['v4_confidence']] for d in review['decisions'] if d['accepted']]
        refinement = []
        cache_audit = {}
        options = json.loads(args.options.read_text(encoding='utf-8-sig'))
        if rows and options.get('refine_title_rois'):
            import numpy as np
            from rapidocr_onnxruntime.ch_ppocr_det import TextDetector
            from rapidocr_onnxruntime.ch_ppocr_det.utils import DetPreProcess
            detector_config=dict(model_path=str(args.v4_model.with_name('ch_PP-OCRv4_det_infer.onnx')),
                limit_type='max',limit_side_len=960,mean=[0.5]*3,std=[0.5]*3,
                intra_op_num_threads=2,inter_op_num_threads=1,use_cuda=args.device=='cuda',use_dml=False)
            if models is not None and 'geometry_detector' in models:
                detector=models['geometry_detector']
            else:
                detector=TextDetector(detector_config)
                if models is not None: models['geometry_detector']=detector
            checked_providers(detector.infer.session)
            detector.get_preprocess=lambda max_wh: DetPreProcess(960,'max',detector.mean,detector.std)
            image=cv2.imread(str(args.image))
            def bounds(points):
                a=np.asarray(points);return [float(a[:,0].min()),float(a[:,1].min()),float(a[:,0].max()),float(a[:,1].max())]
            def overlap(a,b):
                inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                return inter/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)
            for row in rows:
                b=bounds(row[0])
                if b[2]-b[0] > (b[3]-b[1])*1.15:
                    refinement.append(dict(original_points=row[0],skipped='horizontal_title_preserve_tilted_geometry'))
                    continue
                mx=max(20,int((b[2]-b[0])*.2));my=max(20,int((b[3]-b[1])*.2))
                x1=max(0,int(b[0])-mx);y1=max(0,int(b[1])-my)
                x2=min(image.shape[1],int(b[2])+mx);y2=min(image.shape[0],int(b[3])+my)
                boxes,seconds=detector(image[y1:y2,x1:x2])
                candidates=[] if boxes is None else [box+np.array([x1,y1],dtype=np.float32) for box in boxes]
                best=max(candidates,key=lambda box:overlap(b,bounds(box)),default=None)
                iou=overlap(b,bounds(best)) if best is not None else 0
                audit=dict(original_points=row[0],roi=[x1,y1,x2,y2],seconds=float(seconds),iou=iou)
                if iou>=0.5:
                    row[0]=best.tolist();audit['refined_points']=row[0]
                refinement.append(audit)
            del detector
        if rows:
            locate(args.image,args.target,output,0.0 if args.all_texts else 1.0,draw_labels=False,supplied_ocr=rows,all_texts=args.all_texts,
                   flat_seam_extent=options.get('flat_seam_extent',False), geometry_cache=True, geometry_audit=cache_audit)
        else:
            (output/f'{args.image.stem}_hybrid.json').write_text('[]',encoding='utf8')
        emitted=json.loads((output/f'{args.image.stem}_hybrid.json').read_text(encoding='utf8'))
        if args.all_texts and [record['text'] for record in emitted]!=[row[1] for row in rows]:
            raise RuntimeError('All-text geometry dropped or reordered accepted OCR records')
        (output/'geometry.json').write_text(json.dumps(dict(work_seconds=time.perf_counter()-started,
            peak_rss_mib=memory(),emitted_count=len(emitted),accepted_count=len(rows),title_refinement=refinement,cache_audit=cache_audit)),encoding='utf8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('--target',required=True)
    parser.add_argument('--query-title')
    parser.add_argument('--options',type=Path,required=True)
    parser.add_argument('--v4-model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--stage',choices=['scan','review','geometry'])
    parser.add_argument('--all-texts',action='store_true',help='Blind full-image evaluation: review all detected text without target-title hints')
    parser.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    parser.add_argument('--shelf-roi',type=int,nargs=4)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if args.stage:
        worker(args)
        return
    start=time.perf_counter()
    # Each process exits before the next model loads: no tiny/v4 coexistence.
    for stage in ['scan','review','geometry']:
        command=[sys.executable,str(Path(__file__).resolve()),str(args.image),'--target',args.target,
                 '--options',str(args.options),'--v4-model',str(args.v4_model),'--output',str(args.output),'--stage',stage]
        command+=['--device',args.device]
        if args.shelf_roi is not None:command+=['--shelf-roi']+[str(v) for v in args.shelf_roi]
        if args.query_title:command+=['--query-title',args.query_title]
        if args.all_texts:
            command.append('--all-texts')
        with (args.output/f'{stage}.log').open('w',encoding='utf8') as log:
            subprocess.run(command,check=True,timeout=300,stdout=log,stderr=subprocess.STDOUT)
    records=[json.loads((args.output/f'{s}.json').read_text(encoding='utf8')) for s in ['scan','review','geometry']]
    report=dict(target=args.target,total_wall_seconds=time.perf_counter()-start,
                all_texts=args.all_texts,
                device=args.device,
                max_worker_peak_mib=max(r['peak_rss_mib'] for r in records),
                candidate_count=len(records[0]['candidates']),accepted_count=records[2]['accepted_count'],
                image_sha256=hashlib.sha256(args.image.read_bytes()).hexdigest(),
                v4_model_sha256=hashlib.sha256(args.v4_model.read_bytes()).hexdigest(),
                scope='Blind all-detected-text evaluation; accepted_count counts text regions, not books; no LED command emitted' if args.all_texts else 'Experimental OCR evidence only; agreement is not a guarantee; no LED command emitted')
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
