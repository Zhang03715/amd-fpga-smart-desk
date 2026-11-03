import base64
from datetime import datetime
import hashlib
import io
import json
import math
import re

ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
MAX_BODY = 12 * 1024 * 1024


class ProtocolError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def decode_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except (ValueError, UnicodeError):
        raise ProtocolError(400, 'invalid JSON')


def validate(payload, max_image_bytes=8*1024*1024):
    from PIL import Image
    try:
        if not isinstance(payload, dict) or type(payload.get('v')) is not int or payload['v'] != 1:
            raise ValueError('unsupported version')
        if not isinstance(payload.get('request_id'), str) or not ID.fullmatch(payload['request_id']):
            raise ValueError('invalid request_id')
        action, params = payload.get('action'), payload.get('params')
        if action not in ('book.scan', 'book.find','paper.classify') or not isinstance(params, dict):
            raise ValueError('unsupported action')
        if action == 'book.find':
            if set(params)-{'shelf_roi'} != {'title'} or not isinstance(params['title'], str) or not 1 <= len(params['title'].strip()) <= 200:
                raise ValueError('invalid title')
        elif action=='paper.classify' and params not in ({},{'operation':'wrong_question'}):
            raise ValueError('unsupported paper parameters')
        elif action!='paper.classify' and set(params)-{'shelf_roi','query_title'}:
            raise ValueError('unsupported scan parameters')
        if 'query_title' in params and (not isinstance(params['query_title'],str) or not 1<=len(params['query_title'].strip())<=200):
            raise ValueError('invalid query title')
        source = payload['source']
        if not isinstance(source, dict) or source.get('kind') not in ('image', 'camera') or type(source.get('live')) is not bool:
            raise ValueError('invalid source')
        if source['live'] != (source['kind'] == 'camera'):
            raise ValueError('source live/kind mismatch')
        if not isinstance(source.get('capture_id'), str) or not 1 <= len(source['capture_id']) <= 128:
            raise ValueError('invalid capture_id')
        if source.get('clock') not in ('unknown', 'client_read_completion'):
            raise ValueError('invalid source clock')
        if source.get('captured_at') is not None and (not isinstance(source['captured_at'], str) or len(source['captured_at']) > 80):
            raise ValueError('invalid captured_at')
        if source.get('captured_at') is not None:
            stamp = datetime.fromisoformat(source['captured_at'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('captured_at must include timezone')
        age = source.get('age_seconds')
        if type(age) not in (int, float) or not math.isfinite(age) or age < 0:
            raise ValueError('invalid source age')
        if source['kind'] == 'camera' and age > 10:
            raise ValueError('stale camera capture')
        encoded = payload['image']
        if not isinstance(encoded, dict) or encoded.get('encoding') != 'base64' or not isinstance(encoded.get('data'), str):
            raise ValueError('invalid image encoding')
        if len(encoded['data']) > ((max_image_bytes+2)//3)*4:
            raise ProtocolError(413, 'image too large')
        data = base64.b64decode(encoded['data'], validate=True)
        if not data or len(data) > max_image_bytes:
            raise ProtocolError(413, 'image size out of range')
        digest = hashlib.sha256(data).hexdigest()
        if encoded.get('sha256') != digest:
            raise ValueError('image SHA256 mismatch')
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ('JPEG', 'PNG') or im.width * im.height > 30_000_000:
                raise ValueError('unsupported image or dimensions')
            dimensions = [im.width, im.height]
            if 'shelf_roi' in params:
                roi=params['shelf_roi']
                if (not isinstance(roi,list) or len(roi)!=4 or any(type(v) is not int for v in roi)
                    or not 0<=roi[0]<roi[2]<=im.width or not 0<=roi[1]<roi[3]<=im.height):
                    raise ValueError('invalid shelf ROI')
            suffix = '.jpg' if im.format == 'JPEG' else '.png'
            im.verify()
        metadata = {k: v for k, v in payload.items() if k != 'image'}
        metadata['image'] = {'sha256': digest, 'dimensions': dimensions}
        fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True, ensure_ascii=False,
                                                 allow_nan=False).encode()).hexdigest()
        return data, suffix, metadata, fingerprint
    except ProtocolError:
        raise
    except Exception as exc:
        raise ProtocolError(400, str(exc) if isinstance(exc, ValueError) else 'invalid request/image') from exc
