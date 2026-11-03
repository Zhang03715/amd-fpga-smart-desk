"""Download pinned official local inference assets into this project only."""
import hashlib,json,time,urllib.request,zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=[('Qwen3-4B-Q4_K_M.gguf','https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf',2497280256,'7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'),
       ('llama-b11985-bin-win-cuda-12.4-x64.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11985/llama-b11985-bin-win-cuda-12.4-x64.zip',None,None),
       ('cudart-llama-bin-win-cuda-12.4-x64.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11985/cudart-llama-bin-win-cuda-12.4-x64.zip',None,None)]
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()
def download(item):
    name,url,size,sha=item;root=ROOT/'.build-tools/paper-classifier';root.mkdir(parents=True,exist_ok=True)
    target=root/name;part=target.with_suffix(target.suffix+'.part')
    if target.exists() and (size is None or target.stat().st_size==size) and (sha is None or digest(target)==sha):return target
    for attempt in range(4):
        try:
            offset=part.stat().st_size if part.exists() else 0
            headers={'User-Agent':'AMD-Local-Paper-Classifier'}
            if offset:headers['Range']='bytes=%d-'%offset
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=45) as response:
                append=offset and response.status==206
                total=offset if append else 0;last=total
                with part.open('ab' if append else 'wb') as stream:
                    while True:
                        data=response.read(4*1024*1024)
                        if not data:break
                        stream.write(data);total+=len(data)
                        if total-last>=64*1024*1024:print(name,total,flush=True);last=total
            if size is not None and part.stat().st_size!=size:raise ValueError('Unexpected size')
            if sha is not None and digest(part)!=sha:raise ValueError('SHA256 mismatch')
            part.replace(target);print('DOWNLOAD_READY',name,target.stat().st_size,flush=True);return target
        except Exception as error:
            print('DOWNLOAD_RETRY',name,type(error).__name__,flush=True)
            if attempt==3:raise
            time.sleep(2)
def main():
    with ThreadPoolExecutor(max_workers=3) as pool:paths=list(pool.map(download,FILES))
    runtime=ROOT/'.build-tools/paper-classifier/runtime';runtime.mkdir(exist_ok=True)
    for path in paths[1:]:
        with zipfile.ZipFile(path) as z:
            if z.testzip():raise ValueError('Corrupt runtime zip')
            for info in z.infolist():
                dest=(runtime/info.filename).resolve()
                if not dest.is_relative_to(runtime.resolve()):raise ValueError('Unsafe archive path')
            z.extractall(runtime)
    metadata=[dict(name=p.name,bytes=p.stat().st_size,sha256=digest(p),source=item[1],upstream_hash_checked=bool(item[3])) for p,item in zip(paths,FILES)]
    (runtime.parent/'verified-assets.json').write_text(json.dumps(metadata,indent=2))
    print('LOCAL_CLASSIFIER_ASSETS_READY',flush=True)
if __name__=='__main__':main()
