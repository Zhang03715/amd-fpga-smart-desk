"""Exact input/bias conversion for uint8 activations and symmetric int8 weights.

This handles accumulation only. Output zero points and ONNX requantization
rounding remain separate requirements; the current RTL cannot consume a full
QLinearConv contract directly.
"""
import numpy as np


def requantize_u8(accumulator, multiplier, shift, output_zero_point):
    """Exact integer multiplier/2**shift, nearest-even, then zero point/saturate.

    Float ONNX scales still need approximation and runtime comparison; this
    arithmetic contract alone does not prove QLinearConv equivalence.
    """
    for value, lo, hi in [(accumulator, -(1<<31), (1<<31)-1),
                          (multiplier, 0, (1<<31)-1), (shift, 0, 62),
                          (output_zero_point, 0, 255)]:
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError('Outside uint8 requantization contract')
    product = accumulator*multiplier
    magnitude = abs(product)
    quotient, remainder = divmod(magnitude, 1<<shift)
    divisor = 1<<shift
    if 2*remainder > divisor or (2*remainder == divisor and quotient % 2):
        quotient += 1
    signed = -quotient if product < 0 else quotient
    return min(255, max(0, signed+output_zero_point))


def prepare_accumulation(activations, weights, bias, input_zero_point):
    x, w, b = map(np.asarray, (activations, weights, bias))
    if x.dtype != np.uint8 or x.ndim != 2 or not x.shape[0]:
        raise ValueError('Expected nonempty P,C uint8 activations')
    if w.dtype != np.int8 or w.ndim != 2 or not w.shape[0]:
        raise ValueError('Expected nonempty O,C symmetric int8 weights')
    if not 1 <= x.shape[1] <= 480 or w.shape[1] != x.shape[1]:
        raise ValueError('Expected matching 1..480 input channels')
    if b.dtype != np.int32 or b.shape != (w.shape[0],):
        raise ValueError('Expected O int32 bias values')
    if type(input_zero_point) is not int or not 0 <= input_zero_point <= 255:
        raise ValueError('Expected scalar uint8 input zero point')
    # (x-z)*w+b == (x-128)*w + b+(128-z)*sum(w), exactly.
    adjusted = b.astype(np.int64)+(128-input_zero_point)*w.astype(np.int64).sum(axis=1)
    bound = np.abs(adjusted)+128*np.abs(w.astype(np.int64)).sum(axis=1)
    if np.any(bound > (1<<31)-1):
        raise OverflowError('Converted bias/accumulation may exceed int32')
    return (x.astype(np.int16)-128).astype(np.int8), adjusted.astype(np.int32)
