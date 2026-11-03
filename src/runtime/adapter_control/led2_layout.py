"""User-confirmed 60-pixel LED2 chain. Physical labels are one-based."""
class Led2Layout:
    channel=1
    physical_count=60
    horizontal=tuple(range(30,44))  # Physical 31..44, 14 pixels.
    vertical=tuple(range(29,20,-1))  # Physical 30..22, 9 pixels in user order.
    active=tuple(range(21,44))

    @classmethod
    def info(cls):
        return dict(channel=cls.channel,physical_count=cls.physical_count,
                    index_base=0,physical_number_base=1,
                    horizontal_indices=list(cls.horizontal),vertical_indices=list(cls.vertical),
                    inactive_indices=[i for i in range(cls.physical_count) if i not in cls.active],
                    spatial_calibration_required=True)

    @classmethod
    def pixels(cls,horizontal=(),vertical=(),horizontal_rgb=(0,255,0),vertical_rgb=(0,0,255)):
        pixels=[(0,0,0)]*cls.physical_count
        for selected,mapping,color in [(horizontal,cls.horizontal,horizontal_rgb),
                                       (vertical,cls.vertical,vertical_rgb)]:
            if len(color)!=3 or any(type(v) is not int or not 0<=v<=255 for v in color):
                raise ValueError('invalid_rgb')
            for logical in selected:
                if type(logical) is not int or not 0<=logical<len(mapping):
                    raise ValueError('invalid_segment_index')
                pixels[mapping[logical]]=tuple(color)
        return pixels
