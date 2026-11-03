"""Explicit byte layout for experimental stream; no PYNQ or device access."""
import struct
import numpy as np


def activation_packet(values):
    x=np.asarray(values)
    if x.dtype!=np.int8 or x.ndim!=1 or not 1<=len(x)<=480:
        raise ValueError('Expected 1..480 int8 channels')
    return x.tobytes()


def weight_packet(weights):
    w=np.asarray(weights)
    if w.dtype!=np.int8 or w.ndim!=2 or w.shape[0]!=8 or not 1<=w.shape[1]<=480:
        raise ValueError('Expected 8 x C int8 weights')
    # One 64-bit word per input channel; lane0 is the low byte.
    return np.ascontiguousarray(w.T).tobytes()


def unpack_results(payload, lane_mask=255):
    if len(payload)!=32 or type(lane_mask)!=int or not 0<=lane_mask<=255:
        raise ValueError('Expected 8 little-endian int32 result words and valid mask')
    values=struct.unpack('<8i',payload)
    if any(not -128<=v<=127 for v in values):
        raise ValueError('Result is not sign-extended int8')
    if any(v!=0 and not lane_mask&(1<<i) for i,v in enumerate(values)):
        raise ValueError('Inactive lane is not zero')
    return np.asarray(values,np.int8)
