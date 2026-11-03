"""Read a fresh snapshot from this board only, preserving capture timestamps."""
from datetime import datetime
import math
import time
from urllib.parse import urlsplit
from urllib.request import build_opener,ProxyHandler,HTTPRedirectHandler
from .client import MAX_IMAGE,ClientError


def read_snapshot(url,timeout=5):
    parsed=urlsplit(url)
    if (parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1')
            or parsed.username or parsed.password or parsed.fragment):
        raise ClientError('snapshot must use board loopback HTTP')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):
            raise ClientError('camera snapshot redirects are forbidden')
    with build_opener(ProxyHandler({}),NoRedirect()).open(url,timeout=timeout) as response:
        data=response.read(MAX_IMAGE+1)
        try:
            info=dict(captured_at=response.headers['X-Captured-At'],
                      captured_monotonic=float(response.headers['X-Captured-Monotonic']),
                      actual_width=int(response.headers['X-Width']),actual_height=int(response.headers['X-Height']),
                      device=response.headers['X-Camera-Device'],sequence=int(response.headers['X-Sequence']))
        except (TypeError,ValueError,KeyError) as exc:
            raise ClientError('invalid camera snapshot metadata') from exc
    age=time.monotonic()-info['captured_monotonic']
    if not isinstance(info['captured_at'],str) or not info['device']:
        raise ClientError('missing camera snapshot metadata')
    stamp=datetime.fromisoformat(info['captured_at'].replace('Z','+00:00'))
    if (not data.startswith(b'\xff\xd8') or len(data)>MAX_IMAGE or not math.isfinite(age)
            or not 0<=age<=2 or not stamp.tzinfo or not 0<info['actual_width']<=10000
            or not 0<info['actual_height']<=10000 or info['sequence']<1):
        raise ClientError('invalid or stale camera snapshot')
    return data,info
