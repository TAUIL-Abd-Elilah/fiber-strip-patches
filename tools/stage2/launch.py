"""Start chain.py detached: CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB | BelowNormal (no
DETACHED_PROCESS: its children have died with 0xC000013A here), stdout+stderr to chain_stdout.log, PID in pid.txt. The
chain sets its own affinity to cores 0-11 before it spawns anything. Poll chain_status.json, chain.log, bandNN/status.json,
bandNN/DONE and CHAIN_DONE; never the process name.

    python -I -B launch.py [chain.py arguments, e.g. --retry-failed]
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'
TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
cmd = [PY, '-I', '-B', '-u', str(TOOLS/'chain.py'), *sys.argv[1:]]
env = dict(os.environ, CUDA_VISIBLE_DEVICES='-1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
out = open(ROOT/'chain_stdout.log', 'a', encoding='utf-8')
flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS
try:
    p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(ROOT), env=env,
                         creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
    breakaway = True
except OSError:
    p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(ROOT), env=env,
                         creationflags=flags)
    breakaway = False
(ROOT/'pid.txt').write_text(f'{p.pid}\n')
(ROOT/'launch.json').write_text(json.dumps(dict(pid=p.pid, cmd=cmd, launched=time.strftime('%Y-%m-%d %H:%M:%S'),
                                                breakaway_from_job=breakaway, launcher=sys.argv[0]), indent=1))
print(json.dumps(dict(pid=p.pid, breakaway_from_job=breakaway, cmd=' '.join(cmd))))
