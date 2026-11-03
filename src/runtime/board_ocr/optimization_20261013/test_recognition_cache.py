import unittest
import numpy as np
from .recognition_cache import RecognitionCache


class RecognitionCacheTests(unittest.TestCase):
    def test_only_identical_pixels_shape_and_call_order_are_reused(self):
        calls=[]
        def recognize(images):
            calls.append(images)
            return [[str(int(image.sum())),.9] for image in images],.2
        cache=RecognitionCache(recognize)
        a=np.zeros((3,4,3),np.uint8);b=a.copy();b[0,0]=1
        first,_=cache([a,b]);first[0][0]='mutated'
        rows,seconds=cache([a.copy(),b.copy()])
        self.assertEqual(rows[0][0],'0');self.assertEqual(seconds,0)
        cache([b,a]);cache([a.reshape(4,3,3),b]);cache([a])
        self.assertEqual(len(calls),4);self.assertEqual(cache.info()['hits'],1)
        RecognitionCache(recognize)([a,b])
        self.assertEqual(len(calls),5)  # no results cross a frame boundary

    def test_cache_capacity_is_bounded(self):
        cache=RecognitionCache(lambda images:([['x',.9]],.1),limit=2)
        for i in range(5):cache([np.full((2,2,3),i,np.uint8)])
        self.assertEqual(len(cache.entries),2)


if __name__=='__main__':unittest.main()
