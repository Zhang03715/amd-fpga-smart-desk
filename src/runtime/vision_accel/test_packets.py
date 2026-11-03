import struct
import unittest
import numpy as np
from .packets import activation_packet,weight_packet,unpack_results


class PacketTests(unittest.TestCase):
    def test_signed_activation_bytes_and_lengths(self):
        self.assertEqual(activation_packet(np.array([-128,-1,0,127],np.int8)),bytes([128,255,0,127]))
        for n in [0,481]:
            with self.assertRaises(ValueError):activation_packet(np.zeros(n,np.int8))

    def test_weight_lanes_are_channel_major(self):
        w=np.arange(24,dtype=np.int8).reshape(8,3)
        self.assertEqual(weight_packet(w)[:8],bytes([0,3,6,9,12,15,18,21]))
        self.assertEqual(len(weight_packet(w)),24)

    def test_sign_extension_and_tail_validation(self):
        np.testing.assert_array_equal(unpack_results(struct.pack('<8i',-128,-1,127,0,0,0,0,0),7),[-128,-1,127,0,0,0,0,0])
        for data,mask in [(struct.pack('<8i',255,0,0,0,0,0,0,0),255),(struct.pack('<8i',1,0,0,0,0,0,0,0),0),(b'bad',255)]:
            with self.assertRaises(ValueError):unpack_results(data,mask)


if __name__=='__main__':unittest.main()
