"""Optional native batched writes through the existing adapter GPIO mapping."""
import ctypes
from pathlib import Path


def enable(bridge, library=None):
    path = Path(library) if library else Path(__file__).with_name('lcd_native.so')
    lib = ctypes.CDLL(str(path.resolve()))
    function = lib.lcd_data_write
    function.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                         ctypes.c_double, ctypes.POINTER(ctypes.c_uint32)]
    function.restype = ctypes.c_int
    pack = lib.lcd_pack_rgb565
    pack.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    pack.restype = ctypes.c_int
    address = int(bridge.mmio.array.ctypes.data)
    if address % 4:
        raise ValueError('Unaligned GPIO mapping')
    failed = False

    def data_bytes(payload):
        nonlocal failed
        if len(payload) > 4096:
            raise ValueError('Native LCD batch exceeds 4096 bytes')
        with bridge.lock:
            if failed:
                raise RuntimeError('Native LCD failed; reinitialize before further use')
            data = ctypes.create_string_buffer(bytes(payload))
            toggle = ctypes.c_uint32(bridge.toggle)
            result = function(address, data, len(payload), bridge.timeout,
                              ctypes.byref(toggle))
            bridge.toggle = toggle.value
            if result != len(payload):
                failed = True
                raise TimeoutError(f'native_lcd_transfer_failed:{result}')
    bridge.data_bytes = data_bytes
    def encode_rgb565(image):
        if not 1 <= image.width <= 320 or not 1 <= image.height <= 320:
            raise ValueError('Invalid native conversion dimensions')
        raw = image.convert('RGB').tobytes()
        source = ctypes.create_string_buffer(raw)
        result = ctypes.create_string_buffer(image.width*image.height*2)
        count = pack(source, image.width*image.height, result)
        if count != len(result):
            raise RuntimeError('Native RGB565 conversion failed')
        return result.raw
    bridge.encode_rgb565 = encode_rgb565
    bridge._native_lcd_library = lib
