"""Launch run_band.py detached (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP), stdout+stderr to RUN_DIR/runner_stdout.log,
and record the PID in RUN_DIR/pid.txt. Poll RUN_DIR/status.json, run.log and DONE; never by process name."""
import json
from pathlib import Path
import subprocess
import sys
import time

PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'
ROOT = Path('C:/VesuviusTemp/nov_strips/infer')
cmd = [PY, '-I', '-B', '-u', str(ROOT/'tools'/'run_band.py'), '--plan', str(ROOT/'plan'/'band_plan.json'),
       '--runplan', str(ROOT/'plan'/'runplan_band.tsv'), '--afv', str(ROOT/'plan'/'band.afv'), '--root', str(ROOT),
       '--min-free-gib', '25', '--workers', '2', '--threads', '8']
out = open(ROOT/'runner_stdout.log', 'a', encoding='utf-8')
p = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(ROOT),
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
(ROOT/'pid.txt').write_text(f'{p.pid}\n')
(ROOT/'launch.json').write_text(json.dumps(dict(pid=p.pid, cmd=cmd, launched=time.strftime('%Y-%m-%d %H:%M:%S'),
                                                launcher=sys.argv[0]), indent=1))
print(json.dumps(dict(pid=p.pid, cmd=' '.join(cmd))))
