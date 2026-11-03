"""Generate the opt-in derivative; fail if the source no longer matches."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT/'tools/run_verified_lookup.py').read_text(encoding='utf8')


def replace(before, after):
    global source
    if source.count(before) != 1:
        raise RuntimeError(f'Expected exactly one source block: {before!r}')
    source = source.replace(before, after)


replace('ROOT = Path(__file__).resolve().parents[1]', 'ROOT = Path(__file__).resolve().parents[2]')
replace('rows, stages = engine(image)', '''from board_ocr.optimization_20261013.reuse import scan_with_crops
        rows, stages, reused_crops = scan_with_crops(engine, image)''')
replace('''crops = engine.get_crop_img_list(image, [np.asarray(c['points'],dtype=np.float32) for c in candidates])
            crops, _, _ = engine.text_cls(crops)''', '''if reused_crops is not None:
                crops = [reused_crops[c['id']] for c in candidates]
                crop_reuse = dict(reused_count=len(crops), fallback_count=0)
            else:
                crops = engine.get_crop_img_list(image, [np.asarray(c['points'],dtype=np.float32) for c in candidates])
                crops, _, _ = engine.text_cls(crops)
                crop_reuse = dict(reused_count=0, fallback_count=len(crops))''')
replace('''if candidates:
            import numpy''', '''crop_reuse = dict(reused_count=0, fallback_count=0)
        if candidates:
            import numpy''')
replace('report = dict(candidates=candidates,', 'report = dict(crop_reuse=crop_reuse, candidates=candidates,')
replace('from expanded_title_review import use_expanded_text', '''from expanded_title_review import use_expanded_text
        from board_ocr.optimization_20261013.reuse import expansion_can_change_selection''')
replace("if c.get('expanded_crop_file'):", "if c.get('expanded_crop_file') and expansion_can_change_selection(text, None if args.all_texts else args.target):")
replace('decision = dict(accepted=', '''if c.get('expanded_crop_file') and not extra:
                extra = dict(expanded_review_skipped='cannot_satisfy_existing_strict_expansion_rule')
            decision = dict(accepted=''')
replace('refinement = []', 'refinement = []\n        cache_audit = {}')
replace("flat_seam_extent=options.get('flat_seam_extent',False))", "flat_seam_extent=options.get('flat_seam_extent',False), geometry_cache=True, geometry_audit=cache_audit)")
replace('accepted_count=len(rows),title_refinement=refinement)', 'accepted_count=len(rows),title_refinement=refinement,cache_audit=cache_audit)')
replace('"""Experimental tiny scan -> separate v4 review -> existing spine geometry."""',
        '"""Opt-in derivative: exact crop reuse, strict expansion pruning, request-local geometry reuse. Models remain in separate processes for ARM memory limits."""')
(Path(__file__).with_name('run_optimized_lookup.py')).write_text(source, encoding='utf8')
