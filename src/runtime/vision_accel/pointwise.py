"""Symmetric int8 1x1 reference with exact signed arithmetic semantics."""
import numpy as np


def requantize(value, multiplier, shift):
    """Nonnegative Q multiplier; nearest rounding, ties away from zero.

    Integer multiplication must fit signed 64 bits. Output saturates to int8.
    No activation zero points, batch norm, or nonlinear activation is fused.
    """
    if type(multiplier) is not int or not 0<=multiplier<=2147483647:
        raise ValueError('multiplier outside unsigned 31-bit contract')
    if type(shift) is not int or not 0<=shift<=62:
        raise ValueError('shift outside 0..62')
    product=int(value)*multiplier
    if not -(1<<63)<=product<(1<<63):
        raise OverflowError('requantization product overflows int64')
    rounded=abs(product)
    if shift:
        rounded=(rounded+(1<<(shift-1)))>>shift
    if product<0:
        rounded=-rounded
    return max(-128,min(127,rounded))


def pointwise_reference(activations, weights, bias, multipliers, shifts):
    """P,C input; O,C weights; O bias/scales -> P,O outputs.

    Conservative bound ensures every accumulation order fits int32. Reject
    overflow configurations instead of silently wrapping or clipping sums.
    """
    x=np.asarray(activations);w=np.asarray(weights);b=np.asarray(bias)
    if x.dtype!=np.int8 or w.dtype!=np.int8 or x.ndim!=2 or w.ndim!=2:
        raise ValueError('Expected int8 matrices')
    if x.shape[1]!=w.shape[1] or min(*x.shape,*w.shape)<=0:
        raise ValueError('Invalid matrix dimensions')
    if b.dtype!=np.int32 or b.shape!=(w.shape[0],):
        raise ValueError('Expected int32 output-channel bias')
    if len(multipliers)!=len(b) or len(shifts)!=len(b):
        raise ValueError('One multiplier/shift required per output channel')
    xbound=np.abs(x.astype(np.int64)).max(axis=0)
    bound=np.abs(w.astype(np.int64))@xbound+np.abs(b.astype(np.int64))
    if np.any(bound>2147483647):
        raise OverflowError('Potential int32 accumulator overflow')
    accum=x.astype(np.int64)@w.astype(np.int64).T+b.astype(np.int64)
    result=np.empty(accum.shape,np.int8)
    for p in range(len(x)):
        for o in range(len(b)):
            result[p,o]=requantize(int(accum[p,o]),multipliers[o],shifts[o])
    return accum.astype(np.int32),result
