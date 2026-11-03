"""Button navigation and display rendering independent of board access."""
from PIL import Image, ImageDraw, ImageFont, ImageOps


class Buttons:
    def __init__(self):
        self.previous = 0

    def update(self, pressed):
        rising = pressed & ~self.previous
        self.previous = pressed
        return [name for i, name in enumerate(('up', 'down', 'ok', 'back')) if rising & (1 << i)]


class Menu:
    entries = ('Status', 'Pomodoro 25 min', 'Camera preview', 'Lights off', 'Book result')

    def __init__(self, service, font=None):
        self.service, self.font = service, font
        self.index, self.page = 0, 'menu'
        self.camera = None
        self.camera_source = 'No camera connected'
        self.message = 'Ready'
        self._fonts = {}

    def key(self, key):
        if key == 'back':
            self.page = 'menu'
        elif self.page == 'menu':
            if key == 'up': self.index = (self.index - 1) % len(self.entries)
            elif key == 'down': self.index = (self.index + 1) % len(self.entries)
            elif key == 'ok':
                self.page = ('status', 'timer', 'camera', 'lights', 'book')[self.index]
                if self.page == 'timer' and self.service.timer_status()['state'] == 'idle':
                    self.service.execute('timer.start', {'minutes': 25})
                if self.page == 'lights':
                    try:
                        result = self.service.execute('light.scene', {'scene': 'off'})
                        self.message = 'Lights off applied' if result.get('applied') else 'Lights preview / not applied'
                    except ValueError as exc:
                        self.message = str(exc)
        elif self.page == 'book' and key == 'ok':
            self.service.execute('book.cancel', {})

    def render(self, size=(240, 320)):
        image = Image.new('RGB', size, '#101824')
        draw = ImageDraw.Draw(image)
        if self.font not in self._fonts:
            if self.font:
                self._fonts[self.font] = ImageFont.truetype(self.font, 16)
            else:
                try:
                    self._fonts[self.font] = ImageFont.load_default(size=16)
                except TypeError:  # Board Pillow predates the size argument.
                    self._fonts[self.font] = ImageFont.load_default()
        font = self._fonts[self.font]
        def text(y, value, fill='white'):
            value = str(value)
            if draw.textlength(value,font=font)>size[0]-20:
                while value and draw.textlength(value+'...',font=font)>size[0]-20:
                    value=value[:-1]
                value+='...'
            draw.text((10, y), value, font=font, fill=fill)
        text(12, 'PYNQ-Z2 Desk')
        if self.page == 'menu':
            for i, entry in enumerate(self.entries):
                y = 52 + 40 * i
                if i == self.index: draw.rectangle((5, y - 5, size[0] - 5, y + 26), fill='#215482')
                text(y, entry)
        elif self.page == 'camera':
            text(32, self.camera_source, '#ffd070')
            if self.camera is None: text(60, 'No fresh camera frame')
            else:
                frame = ImageOps.contain(self.camera, (size[0], size[1] - 80))
                image.paste(frame, ((size[0] - frame.width) // 2, 45))
        elif self.page == 'timer':
            timer = self.service.timer_status()
            minutes, seconds = divmod(timer['remaining_seconds'], 60)
            text(65, f'{minutes:02d}:{seconds:02d}')
            text(105, timer['state'])
        elif self.page == 'status':
            text(60, 'SPI / UART / WS2812')
            text(100, 'Hardware test pending', '#ffd070')
        elif self.page == 'book':
            book = self.service.execute('book.status', {})
            text(48, 'Book: ' + book['state'])
            text(82, str(book.get('title', ''))[:22])
            text(120, 'Matches: ' + str(book.get('result', {}).get('match_count', 0)))
            text(155, str(book.get('error') or book.get('guidance') or 'Await voice request')[:26], '#ffd070')
            text(200, 'OK: cancel / dismiss')
            text(230, 'Indicator: not applied')
        else: text(60, self.message)
        text(size[1] - 38, 'UP DOWN OK BACK', '#b5c6d8')
        return image
