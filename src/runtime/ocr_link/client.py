"""Authenticated, bounded LAN OCR client. Results never actuate hardware."""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_IMAGE = 8 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ClientError(RuntimeError):
    pass


class NetworkError(ClientError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Never forward the bearer token to a redirect destination.
        return None


def save_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def read_token(path):
    path = Path(path)
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise ClientError('token file must be private: chmod 600 ' + str(path))
    token = path.read_text(encoding='utf-8').strip()
    if not token or len(token) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ClientError('token must be nonempty printable ASCII without whitespace')
    return token


def make_request(image_bytes, request_id, action, title, source):
    if not REQUEST_ID.fullmatch(request_id):
        raise ClientError('invalid request_id')
    if action not in ('book.find', 'book.scan'):
        raise ClientError('only book.find and book.scan are supported')
    if action == 'book.find' and (not isinstance(title, str) or not title.strip()):
        raise ClientError('book.find requires a nonempty title')
    if action == 'book.scan' and title is not None:
        raise ClientError('book.scan does not accept a title')
    if not 0 < len(image_bytes) <= MAX_IMAGE:
        raise ClientError('image must contain 1..8 MiB')
    if not (image_bytes.startswith(b'\xff\xd8\xff') or image_bytes.startswith(b'\x89PNG\r\n\x1a\n')):
        raise ClientError('only original JPEG/PNG bytes are accepted')
    if source.get('kind') not in ('image', 'camera') or type(source.get('live')) is not bool:
        raise ClientError('invalid image source')
    age = source.get('age_seconds')
    if type(age) not in (int, float) or not math.isfinite(age) or age < 0:
        raise ClientError('source age_seconds must be finite and nonnegative')
    if source['kind'] == 'image' and source['live']:
        raise ClientError('a static image cannot be live')
    return dict(v=1, request_id=request_id, action=action,
                params={'title': title.strip()} if action == 'book.find' else {},
                image={'encoding': 'base64', 'data': base64.b64encode(image_bytes).decode('ascii'),
                       'sha256': hashlib.sha256(image_bytes).hexdigest()}, source=source)


class OCRClient:
    def __init__(self, server, token, request_timeout=10, total_timeout=180, poll_interval=0.5):
        parsed = urlsplit(server)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ClientError('server must be an http(s) origin, without credentials or path')
        for value in (request_timeout, total_timeout, poll_interval):
            if not math.isfinite(value) or value <= 0:
                raise ClientError('timeouts and polling interval must be finite and positive')
        self.server, self.token = server.rstrip('/'), token
        self.request_timeout, self.total_timeout, self.poll_interval = request_timeout, total_timeout, poll_interval
        self.opener = build_opener(NoRedirect())

    def _http(self, path, deadline, payload=None, binary=False):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('OCR total timeout; resume using the same request_id')
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'image/jpeg' if binary else 'application/json'}
        if not binary:headers['Accept-Encoding']='gzip'
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(self.server + path, data=data, headers=headers, method='GET' if data is None else 'POST')
        try:
            with self.opener.open(request, timeout=min(self.request_timeout, remaining)) as response:
                # Read in chunks and enforce the overall deadline between chunks.
                blocks, size = [], 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('OCR total timeout while receiving response')
                    block = response.read(min(65536, MAX_RESPONSE + 1 - size))
                    if not block:
                        break
                    blocks.append(block)
                    size += len(block)
                    if size > MAX_RESPONSE:
                        raise ClientError('server response exceeds 16 MiB')
                raw = b''.join(blocks)
                if response.headers.get('Content-Encoding')=='gzip':
                    import gzip,io
                    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as decoded:raw=decoded.read(MAX_RESPONSE+1)
                    if len(raw)>MAX_RESPONSE:raise ClientError('decoded response exceeds 16 MiB')
        except HTTPError as exc:
            detail = exc.read(2048).decode('utf-8', errors='replace')
            raise ClientError('HTTP %s: %s' % (exc.code, detail)) from exc
        except (URLError, OSError) as exc:
            raise NetworkError('network request failed: ' + str(exc)) from exc
        if binary:
            if not raw.startswith(b'\xff\xd8\xff'):
                raise ClientError('preview response is not JPEG')
            return raw
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ClientError('server returned invalid JSON') from exc
        if not isinstance(result, dict) or result.get('v') != 1:
            raise ClientError('server returned an unsupported protocol')
        return result

    def health(self):
        return self._http('/v1/health', time.monotonic() + self.request_timeout)

    def run(self, payload, output_dir, download_preview=True, *, total_timeout=None):
        budget=self.total_timeout if total_timeout is None else total_timeout
        if type(budget) not in (int,float) or not math.isfinite(budget) or budget<=0:
            raise ClientError('total_timeout must be finite and positive')
        request_id = payload.get('request_id', '')
        if not REQUEST_ID.fullmatch(request_id):
            raise ClientError('invalid request_id')
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        request_path = output / 'request.json'
        if request_path.exists():
            if json.loads(request_path.read_text(encoding='utf-8')) != payload:
                raise ClientError('output directory already contains a different request; use a new directory')
        else:
            save_json(request_path, payload)
        start = time.monotonic()
        deadline = start + budget
        trace = {'v': 1, 'request_id': request_id, 'server': self.server,
                 'image_sha256': payload['image']['sha256'], 'source': payload['source'], 'network_retries': 0}
        upload_end = None
        try:
            while True:
                try:
                    state = self._http('/v1/jobs', deadline, payload)
                    upload_end = time.monotonic()
                    break
                except NetworkError:
                    trace['network_retries'] += 1
                    self._pause(deadline)
            while True:
                if state.get('request_id') != request_id or state.get('status') not in ('queued', 'running', 'succeeded', 'failed'):
                    raise ClientError('server returned an invalid job state')
                save_json(output / 'response.json', state)
                if state['status'] == 'succeeded' and not isinstance(state.get('result'), dict):
                    raise ClientError('successful job response is missing its result object')
                if state['status'] in ('succeeded', 'failed'):
                    break
                self._pause(deadline)
                try:
                    state = self._http('/v1/jobs/' + request_id, deadline)
                except NetworkError:
                    trace['network_retries'] += 1
            trace['ocr_terminal_seconds'] = time.monotonic() - start
            if state['status'] == 'succeeded' and download_preview:
                try:
                    preview = self._http('/v1/jobs/' + request_id + '/preview', deadline, binary=True)
                    (output / 'preview.jpg').write_bytes(preview)
                except (ClientError, TimeoutError) as exc:
                    trace['preview_error'] = str(exc)
            trace['status'] = state['status']
            return state
        except (ClientError, TimeoutError) as exc:
            trace['status'], trace['error'] = 'transport_failed', str(exc)
            raise
        finally:
            trace['client_total_seconds'] = time.monotonic() - start
            trace['upload_seconds'] = None if upload_end is None else upload_end - start
            save_json(output / 'transport.json', trace)

    def _pause(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('OCR total timeout; resume using the same request_id')
        time.sleep(min(self.poll_interval, remaining))
