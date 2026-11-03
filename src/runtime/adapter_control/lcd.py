"""ST7789V 4-wire write-only SPI driver. No I2C despite the SDA silk."""
import time
from dataclasses import dataclass
from PIL import Image, ImageOps


@dataclass
class Panel:
    width: int = 240
    height: int = 320
    x_offset: int = 0
    y_offset: int = 0
    madctl: int = 0
    inversion: bool = False  # Confirmed on the project's physical ST7789 panel.

    def __post_init__(self):
        if not 1 <= self.width <= 320 or not 1 <= self.height <= 320:
            raise ValueError('invalid_panel_size')
        if not 0 <= self.madctl <= 255 or min(self.x_offset, self.y_offset) < 0:
            raise ValueError('invalid_panel_configuration')
        if self.width + self.x_offset > 65536 or self.height + self.y_offset > 65536:
            raise ValueError('panel_address_overflow')


def rgb565(image):
    result = bytearray()
    for red, green, blue in image.convert('RGB').getdata():
        value = (red >> 3) << 11 | (green >> 2) << 5 | blue >> 3
        result.extend((value >> 8, value & 255))
    return bytes(result)


class ST7789:
    def __init__(self, bridge, panel=None, sleep=time.sleep, pump=None, dirty_band_height=None):
        self.bridge, self.panel = bridge, panel or Panel()
        self.sleep, self.pump = sleep, pump
        self.previous = None
        self.dirty_band_height=dirty_band_height
        if dirty_band_height is not None and (type(dirty_band_height) is not int or dirty_band_height<1):
            raise ValueError('invalid_dirty_band_height')

    def command(self, code, data=b''):
        self.bridge.command(1, code)
        self.data(data)

    def data(self, data):
        if hasattr(self.bridge, 'data_bytes'):
            for offset in range(0, len(data), 4096):
                self.bridge.data_bytes(data[offset:offset+4096])
                if self.pump:
                    self.pump()
            return
        for i, byte in enumerate(data):
            self.bridge.command(2, byte)
            if self.pump and i % 8 == 0:
                self.pump()

    def initialize(self):
        self.bridge.command(3, 0)
        self.sleep(0.02)
        self.bridge.command(3, 1)
        self.sleep(0.12)
        self.command(0x01)  # software reset
        self.sleep(0.15)
        self.command(0x11)  # sleep out
        self.sleep(0.12)
        self.command(0x3a, b'\x55')  # RGB565
        self.command(0x36, bytes([self.panel.madctl]))
        self.command(0x21 if self.panel.inversion else 0x20)
        self.command(0x13)  # normal display mode
        self.command(0x29)  # display on
        self.sleep(0.02)
        self.previous = None

    def window(self, box):
        x0, y0, x1, y1 = box  # exclusive end, like Pillow
        p = self.panel
        if not (0 <= x0 < x1 <= p.width and 0 <= y0 < y1 <= p.height):
            raise ValueError('window_outside_panel')
        def pair(a, b):
            return a.to_bytes(2, 'big') + b.to_bytes(2, 'big')
        self.command(0x2a, pair(x0 + p.x_offset, x1 - 1 + p.x_offset))
        self.command(0x2b, pair(y0 + p.y_offset, y1 - 1 + p.y_offset))
        self.command(0x2c)

    def show(self, image):
        from PIL import ImageChops
        size = self.panel.width, self.panel.height
        if image.size != size:
            raise ValueError('frame_size_mismatch')
        frame = image.convert('RGB')
        box = (0, 0, *size) if self.previous is None else ImageChops.difference(frame, self.previous).getbbox()
        if box is None:
            return 0
        # Only changed rectangle, reducing menu transfers; full camera frames
        # may still be slow with this initial per-byte MMIO transport.
        encode = getattr(self.bridge, 'encode_rgb565', rgb565)
        boxes=[box]
        if self.previous is not None and self.dirty_band_height:
            boxes=[]
            for top in range(0,size[1],self.dirty_band_height):
                band=(0,top,size[0],min(top+self.dirty_band_height,size[1]))
                changed=ImageChops.difference(frame.crop(band),self.previous.crop(band)).getbbox()
                if changed:boxes.append((changed[0],changed[1]+top,changed[2],changed[3]+top))
        count=0
        for region in boxes:
            self.window(region)
            payload=encode(frame.crop(region));self.data(payload);count+=len(payload)
        self.previous = frame.copy()
        return count


def camera_frame(image, panel):
    return ImageOps.contain(image.convert('RGB'), (panel.width, panel.height)).copy()


class PreviewLCD:
    def __init__(self, path, panel=None):
        self.path, self.panel = path, panel or Panel()

    def initialize(self):
        pass

    def show(self, image):
        if image.size != (self.panel.width, self.panel.height):
            raise ValueError('frame_size_mismatch')
        image.save(self.path)
        return self.panel.width * self.panel.height * 2
