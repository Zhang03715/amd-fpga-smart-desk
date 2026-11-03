"""Selected offline regression checks; no connected hardware is accessed."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(ROOT / 'build/materialize.py')], check=True)
worktree = ROOT / 'build/worktree'
env = dict(os.environ)
env['PYTHONPATH'] = str(worktree) + os.pathsep + str(worktree / 'voice_bridge')
subprocess.run([
    sys.executable, '-m', 'unittest',
    'ocr_link.test_consensus',
    'ocr_link.test_edition_matching',
    'voice_bridge.test_shelf_calibration',
    'voice_bridge.test_posture_transition',
    'voice_bridge.test_focus_cycle',
], cwd=worktree, env=env, check=True)
