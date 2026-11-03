import unittest
import numpy as np
from .pointwise import pointwise_reference,requantize


class PointwiseTests(unittest.TestCase):
    def test_signed_ties_and_saturation(self):
        self.assertEqual([requantize(v,1,1) for v in [-5,-3,-1,0,1,3,5]],[-3,-2,-1,0,1,2,3])
        self.assertEqual(requantize(-2147483648,1,0),-128)
        self.assertEqual(requantize(2147483647,1,0),127)

    def test_random_vectors_match_scalar_integer_oracle(self):
        rng=np.random.default_rng(104729)
        for channels in [1,3,16,240,480]:
            x=rng.integers(-128,128,(7,channels),dtype=np.int8)
            w=rng.integers(-128,128,(5,channels),dtype=np.int8)
            b=rng.integers(-1000,1000,5,dtype=np.int32)
            multipliers=[1,3,7,13,0];shifts=[8,10,13,14,0]
            acc,y=pointwise_reference(x,w,b,multipliers,shifts)
            for p in range(7):
                for o in range(5):
                    expected=int(b[o])+sum(int(x[p,c])*int(w[o,c]) for c in range(channels))
                    self.assertEqual(int(acc[p,o]),expected)
                    # Independent sign/magnitude division with exact ties.
                    numerator=expected*multipliers[o];denominator=1<<shifts[o]
                    magnitude,remainder=divmod(abs(numerator),denominator)
                    magnitude+=2*remainder>=denominator
                    answer=magnitude if numerator>=0 else -magnitude
                    self.assertEqual(int(y[p,o]),max(-128,min(127,answer)))

    def test_extreme_int8_products_are_not_int8_accumulated(self):
        acc,_=pointwise_reference(np.full((1,480),-128,np.int8),np.full((1,480),-128,np.int8),np.zeros(1,np.int32),[1],[20])
        self.assertEqual(int(acc[0,0]),7864320)

    def test_overflow_rejected(self):
        with self.assertRaises(OverflowError):
            pointwise_reference(np.array([[127]],np.int8),np.array([[127]],np.int8),np.array([2147483647],np.int32),[1],[0])

    def test_bad_scale_and_shapes_rejected(self):
        for scale,shift in [(-1,0),(1,-1),(1,63)]:
            with self.assertRaises(ValueError):
                requantize(1,scale,shift)
        with self.assertRaises(ValueError):
            pointwise_reference(np.zeros((1,3),np.int8),np.zeros((2,4),np.int8),np.zeros(2,np.int32),[1,1],[1,1])


if __name__=='__main__':
    unittest.main()
