"""Persistent child with bounded replies and kill/restart on timeout/failure."""
import json
from pathlib import Path
import queue
import subprocess
import threading


class ResidentRunner:
    def __init__(self,python,root):
        self.python,self.root=str(python),Path(root)
        self.process=None
        self.warmed=False
        self.lock=threading.RLock()

    def _start(self):
        self.responses=queue.Queue(maxsize=2)
        self.process=subprocess.Popen([self.python,'-u','-m','ocr_link.resident_worker'],
            cwd=self.root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',bufsize=1)
        process,responses=self.process,self.responses
        def read():
            try:
                while True:
                    line=process.stdout.readline(65537)
                    if not line or len(line)>65536:break
                    responses.put(line)
            finally:
                try:responses.put_nowait(None)
                except queue.Full:pass
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()

    def run(self,payload,timeout):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.close();self._start()
            try:
                self.process.stdin.write(json.dumps(payload,ensure_ascii=True)+'\n')
                self.process.stdin.flush()
                try:line=self.responses.get(timeout=timeout)
                except queue.Empty:raise TimeoutError('resident GPU pipeline timeout')
                if line is None:raise RuntimeError('resident GPU worker exited')
                result=json.loads(line)
                if result.get('ok') is not True or result.get('output')!=payload['output']:
                    raise RuntimeError('resident GPU worker failed; inspect job logs')
                self.warmed=True
            except Exception:
                self.close()
                raise

    def close(self):
        with self.lock:
            self.warmed=False
            p=self.process
            if p is not None:
                if p.poll() is None:p.kill()
                p.wait(timeout=10)
                p.stdin.close();p.stdout.close()
                self.process=None
