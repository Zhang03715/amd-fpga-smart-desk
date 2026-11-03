import unittest
from .protocol import validate,ProtocolError


class ROITests(unittest.TestCase):
    def payload(self):
        from .client import make_request
        import io
        from PIL import Image
        stream=io.BytesIO();Image.new('RGB',(16,12)).save(stream,format='PNG')
        return make_request(stream.getvalue(),'roi-1','book.scan',None,
            dict(kind='image',capture_id='one',captured_at=None,live=False,age_seconds=0.,clock='unknown'))

    def test_roi_bounds_and_types_are_validated(self):
        # The fixtures are 16x12. Invalid crop metadata must never reach the GPU.
        for roi in ([0,0,17,12],[0,0,16,13],[0,0,0,12],[False,0,16,12],[0,0,16]):
            p=self.payload();p['params']['shelf_roi']=roi
            with self.assertRaises(ProtocolError):validate(p)
        p=self.payload();p['params']['shelf_roi']=[0,0,16,12]
        self.assertEqual(validate(p)[2]['params']['shelf_roi'],[0,0,16,12])


if __name__=='__main__':unittest.main()
