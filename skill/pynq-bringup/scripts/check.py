"""Portable, read-only evidence checker. Python 3.9+; no PYNQ installation needed."""
import argparse,hashlib,json,math,sys
from pathlib import Path

def subset(expected,actual,path='$'):
    if isinstance(expected,dict):
        if not isinstance(actual,dict):raise ValueError(path+': expected object')
        for k,v in expected.items():
            if k not in actual:raise ValueError(path+'.'+k+': missing')
            subset(v,actual[k],path+'.'+k)
    elif isinstance(expected,list):
        if not isinstance(actual,list) or len(expected)!=len(actual):raise ValueError(path+': array length/type')
        for i,(e,a) in enumerate(zip(expected,actual)):subset(e,a,path+'['+str(i)+']')
    elif type(expected)!=type(actual) or expected!=actual:raise ValueError(path+': mismatch')

def verify_manifest(path):
    base=path.resolve().parent;manifest=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(manifest,dict) or not manifest:raise ValueError('manifest must be nonempty object')
    for name,digest in manifest.items():
        if not isinstance(name,str) or Path(name).is_absolute():raise ValueError('invalid member path')
        p=(base/name).resolve()
        try:p.relative_to(base)
        except ValueError:raise ValueError('member escapes manifest directory')
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('invalid SHA256')
        if not p.is_file():raise ValueError('missing artifact: '+name)
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('hash mismatch: '+name)
    return len(manifest)

def verify_timing(path):
    d=json.loads(path.read_text(encoding='utf-8'))
    for key in ('wns_ns','whs_ns'):
        x=d.get(key)
        if type(x) not in (int,float) or not math.isfinite(x) or x<0:raise ValueError(key+': missing, invalid or negative')
    for key in ('drc_errors','unconstrained_paths'):
        if type(d.get(key)) is not int or d[key]!=0:raise ValueError(key+': must be explicit integer zero')
    limits=d.get('resource_limits');usage=d.get('resource_usage')
    if not isinstance(limits,dict) or not limits or not isinstance(usage,dict):raise ValueError('resource limits/usage required')
    for key,limit in limits.items():
        value=usage.get(key)
        if type(limit) not in (int,float) or not math.isfinite(limit) or limit<=0 or type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=limit:raise ValueError('resource exceeds budget or invalid: '+key)
    return d

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path);p.add_argument('--expected',type=Path);p.add_argument('--actual',type=Path);p.add_argument('--timing',type=Path);a=p.parse_args()
    if not any((a.manifest,a.expected,a.actual,a.timing)):p.error('choose at least one check')
    if bool(a.expected)!=bool(a.actual):p.error('--expected and --actual must be supplied together')
    done=[]
    try:
        if a.manifest:verify_manifest(a.manifest);done.append('artifact hashes')
        if a.expected:subset(json.loads(a.expected.read_text(encoding='utf-8')),json.loads(a.actual.read_text(encoding='utf-8')));done.append('golden JSON subset')
        if a.timing:verify_timing(a.timing);done.append('normalized timing/DRC/resources (not constraint completeness)')
        print(json.dumps({'passed':True,'checks':done}));return 0
    except (OSError,ValueError,TypeError,KeyError) as error:
        print(json.dumps({'passed':False,'error':str(error)}));return 1
if __name__=='__main__':sys.exit(main())
