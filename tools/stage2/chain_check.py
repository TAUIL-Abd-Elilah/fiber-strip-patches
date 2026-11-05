"""Read-only look at the chain: processes by PID (from pid.txt and status files), affinity, priority, CPU, log tails, progress.

    python -I -B chain_check.py [seconds_between_cpu_samples]
"""
import json
from pathlib import Path
import shutil
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
wait = float(sys.argv[1]) if len(sys.argv) > 1 else 10.


def describe(pid, label):
    try:
        p = psutil.Process(pid)
        c0 = p.cpu_times()
        return p, c0, label
    except psutil.Error as error:
        print(f'{label} PID {pid}: GONE ({type(error).__name__})')
        return None


chain_pid = int((ROOT/'pid.txt').read_text())
watch = [describe(chain_pid, 'chain')]
if watch[0]:
    for kid in watch[0][0].children():
        if kid.name().lower() == 'python.exe':
            watch.append(describe(kid.pid, 'runner'))
            for g in kid.children():
                if g.name().lower() == 'python.exe':
                    watch.append(describe(g.pid, 'infer'))
watch = [w for w in watch if w]
time.sleep(wait)
for p, c0, label in watch:
    try:
        c1 = p.cpu_times()
        print(f'{label} PID {p.pid}: alive, nice {p.nice()}, affinity {p.cpu_affinity()}, threads {p.num_threads()}, '
              f'RSS {p.memory_info().rss/2**30:.2f} GiB, CPU {(c1.user+c1.system-c0.user-c0.system)/wait:.2f} cores over {wait:g} s, '
              f"cuda env {p.environ().get('CUDA_VISIBLE_DEVICES')}, cmd {' '.join(p.cmdline()[3:5])[:110]}")
    except psutil.Error as error:
        print(f'{label} PID {p.pid}: ended during the sample ({type(error).__name__})')
print('C: free', round(shutil.disk_usage('C:/').free/2**30, 2), 'GiB; machine CPU', psutil.cpu_percent(1), '%, RAM available',
      round(psutil.virtual_memory().available/2**30, 1), 'GiB')
try:
    print('chain_status', {k: v for k, v in json.loads((ROOT/'chain_status.json').read_text()).items() if k != 'bands'})
except Exception as error:  # noqa: BLE001
    print('chain_status unreadable', error)
for b in json.loads((ROOT/'bands.json').read_text())['bands']:
    bd = ROOT/b['name']
    if (bd/'DONE').exists():
        print(b['name'], 'DONE:', (bd/'DONE').read_text().strip()[:200], '| CT_FREED:', (bd/'CT_FREED').read_text().strip() if (bd/'CT_FREED').exists() else None)
    if (bd/'status.json').exists():
        s = json.loads((bd/'status.json').read_text())
        print(b['name'], s['stage'], 'pieces', {k: s['pieces'].get(k) for k in ('planned', 'decisions', 'ok', 'skipped', 'failed', 'skipped_disk', 'decisions_done', 'failed_pieces')},
              'prefetch', {k: s['prefetch'].get(k) for k in ('fetched', 'to_fetch', 'mib', 'mib_per_s')}, 'current', s['current'], 'free min', s.get('c_free_min_gib'), 'updated', s['updated'])
        cur = s['current']
        if isinstance(cur, dict):
            o = bd/'pieces'/f"{cur['piece']}.out"
            lines = [ln for ln in o.read_text(encoding='utf-8', errors='replace').splitlines() if ln.startswith('[infer]')]
            print('  ', cur['piece'], lines[-1] if lines else 'no [infer] line yet')
        lg = bd/'run.log'
        print('  run.log bytes', lg.stat().st_size)
        print('  ', '\n   '.join(ln[:150] for ln in lg.read_text(encoding='utf-8', errors='replace').splitlines()[-4:]))
print('CHAIN_DONE:', (ROOT/'CHAIN_DONE').read_text().strip() if (ROOT/'CHAIN_DONE').exists() else None)
