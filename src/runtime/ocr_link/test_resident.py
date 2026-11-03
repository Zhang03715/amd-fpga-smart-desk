import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from .resident import ResidentRunner


CODE='''import sys,json,time
for line in sys.stdin:
 p=json.loads(line)
 if p.get('hang'):time.sleep(5)
 print(json.dumps(dict(ok=True,output=p['output'])),flush=True)
'''


class ResidentTests(unittest.TestCase):
    def test_reuses_worker_and_restarts_after_timeout(self):
        original=subprocess.Popen
        with tempfile.TemporaryDirectory() as root:
            r=ResidentRunner(sys.executable,root)
            with patch('ocr_link.resident.subprocess.Popen',side_effect=lambda *a,**k:original([sys.executable,'-u','-c',CODE],**k)):
                try:
                    r.run(dict(output='one'),5);pid=r.process.pid
                    r.run(dict(output='two'),5);self.assertEqual(r.process.pid,pid)
                    with self.assertRaises(TimeoutError):r.run(dict(output='three',hang=True),.05)
                    self.assertIsNone(r.process)
                    r.run(dict(output='four'),5);self.assertNotEqual(r.process.pid,pid)
                finally:r.close()
