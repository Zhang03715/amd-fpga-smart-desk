"""Exact input-call reuse for one image and one fixed recognizer instance."""
from collections import OrderedDict
from copy import deepcopy
import hashlib


class RecognitionCache:
    def __init__(self,recognizer,limit=256):
        self.recognizer=recognizer;self.limit=limit;self.entries=OrderedDict()
        self.calls=0;self.hits=0;self.saved_seconds=0.

    def __call__(self,images):
        # Keep list order/grouping intact: never re-batch or reuse similar crops.
        key=tuple((image.shape,image.dtype.str,hashlib.sha256(image.tobytes()).digest()) for image in images)
        self.calls+=1
        if key in self.entries:
            rows,seconds=self.entries[key];self.hits+=1;self.saved_seconds+=float(seconds)
            self.entries.move_to_end(key)
            return deepcopy(rows),0.
        rows,seconds=self.recognizer(images)
        self.entries[key]=(deepcopy(rows),float(seconds))
        if len(self.entries)>self.limit:self.entries.popitem(last=False)
        return rows,seconds

    def info(self):
        return dict(scope='one_image_exact_call',calls=self.calls,hits=self.hits,
                    unique_calls=self.calls-self.hits,estimated_saved_inference_seconds=self.saved_seconds)
