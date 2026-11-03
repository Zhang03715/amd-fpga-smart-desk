"""Conservative request-local crop reuse and strict-title expansion pruning."""
import numpy as np

from verification_policy import title_key


def expansion_can_change_selection(original, target):
    """Exactly derive a skip from use_expanded_text's existing acceptance rule.

    An expansion can only append/prepend 1..2 normalized characters; in a
    target query it must also equal the entire target. Blind OCR always reviews.
    This predicate never authorizes accepting a title by itself.
    """
    if target is None:
        return True
    old, desired = title_key(original), title_key(target)
    return bool(old and 1 <= len(desired)-len(old) <= 2
                and (desired.startswith(old) or desired.endswith(old)))


def scan_with_crops(engine, image):
    """Preserve RapidOCR output; retain its already classified original crops.

    Reuse only when RapidOCR used the exact supplied image and its origin boxes
    equal the crop boxes. Resizing, padding, disabled stages, or an unknown
    ordering force the legacy recrop/classify path. Engine ownership must be
    exclusive during this call (the existing stage worker owns one engine).
    """
    old_crop, old_cls, old_filter = engine.get_crop_img_list, engine.text_cls, engine.filter_result
    captured = {}

    def crop(source, boxes):
        captured['same_image'] = source is image
        captured['boxes'] = np.asarray(boxes).copy()
        return old_crop(source, boxes)

    def classify(crops):
        result = old_cls(crops)
        captured['classified'] = result[0]
        return result

    def filtered(boxes, results):
        output = old_filter(boxes, results)
        good = (captured.get('same_image', False)
                and 'classified' in captured and len(boxes) == len(results)
                and len(boxes) == len(captured['classified'])
                and np.array_equal(captured.get('boxes'), np.asarray(boxes)))
        if good:
            captured['filtered'] = [c for c, r in zip(captured['classified'], results)
                                    if float(r[1]) >= engine.text_score]
        return output

    engine.get_crop_img_list, engine.text_cls, engine.filter_result = crop, classify, filtered
    try:
        rows, stages = engine(image)
    finally:
        engine.get_crop_img_list, engine.text_cls, engine.filter_result = old_crop, old_cls, old_filter
    crops = captured.get('filtered')
    if crops is not None and len(crops) != len(rows or []):
        crops = None
    return rows, stages, crops
