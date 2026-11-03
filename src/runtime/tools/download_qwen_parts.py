"""Bounded parallel HTTP ranges, final official SHA256 mandatory."""
import hashlib,time,urllib.request,sys,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1]/'.build-tools/paper-classifier'
SIZE=2497280256;CHUNK=32*1024*1024
SHA='7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'
URL='https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf'
PARTS=ROOT/'qwen-parts';PARTS.mkdir(exist_ok=True)
NAME='Qwen3-4B-Q4_K_M.gguf'
if '--runtime' in sys.argv:
    NAME='llama-b11985-bin-win-cuda-12.4-x64.zip';SIZE=279764742;SHA=None
    URL='https://github.com/ggml-org/llama.cpp/releases/download/b11985/'+NAME
    PARTS=ROOT/'runtime-parts';PARTS.mkdir(exist_ok=True)
    bad=ROOT/NAME
    if bad.exists() and not zipfile.is_zipfile(bad):bad.replace(bad.with_suffix('.zip.part'))
def fetch(start):
    end=min(SIZE,start+CHUNK)-1;dest=PARTS/str(start);wanted=end-start+1
    for attempt in range(8):
        offset=dest.stat().st_size if dest.exists() else 0
        if offset==wanted:return wanted
        if offset>wanted:raise ValueError('Oversized range file')
        try:
            request=urllib.request.Request(URL+'?download=true&chunk='+str(start),headers={'Range':'bytes=%d-%d'%(start+offset,end),'User-Agent':'AMD-Paper-Classifier'})
            with urllib.request.urlopen(request,timeout=35) as r:
                cr=r.headers.get('Content-Range','')
                if r.status!=206 or not cr.startswith('bytes %d-'%(start+offset)):raise ValueError('Range not honored')
                with dest.open('ab') as stream:
                    left=wanted-offset
                    while left:
                        data=r.read(min(1024*1024,left))
                        if not data:raise OSError('Short range')
                        stream.write(data);left-=len(data)
            print('RANGE_READY',start,end,flush=True);return wanted
        except Exception as error:
            print('RANGE_RETRY',start,type(error).__name__,flush=True)
            if attempt==7:raise
            time.sleep(1)
def main():
    prefix=ROOT/(NAME+'.part')
    if prefix.exists():
        with prefix.open('rb') as stream:
            for start in range(0,prefix.stat().st_size-CHUNK+1,CHUNK):
                data=stream.read(CHUNK);dest=PARTS/str(start)
                if not dest.exists():dest.write_bytes(data)
    ranges=list(range(0,SIZE,CHUNK));done=0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for f in as_completed([pool.submit(fetch,start) for start in ranges]):
            done+=f.result();print('MODEL_PROGRESS',done,SIZE,flush=True)
    target=ROOT/NAME;merged=target.with_suffix('.assembling');h=hashlib.sha256()
    with merged.open('wb') as out:
        for start in ranges:
            with (PARTS/str(start)).open('rb') as part:
                for block in iter(lambda:part.read(4*1024*1024),b''):out.write(block);h.update(block)
    if merged.stat().st_size!=SIZE or SHA is not None and h.hexdigest()!=SHA:raise ValueError('Official model SHA256 mismatch')
    if SHA is None:
        with zipfile.ZipFile(merged) as z:
            if z.testzip():raise ValueError('Runtime ZIP CRC mismatch')
    merged.replace(target);print('ASSET_VERIFIED',NAME,h.hexdigest(),flush=True)
if __name__=='__main__':main()
