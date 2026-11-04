"""run_smoke_B.py: a short CPU fit of one arm on the band dataset with villa main's fit_spiral.py, headless.
The smallest settings that exercise patch loading: the arm's config as written, with optimizer_num_training_steps
cut to --steps (default 20). FIT_SPIRAL_DEVICE=cpu, CUDA hidden, 2 torch threads, BelowNormal priority is the
launcher's job. Writes logs/smoke_<arm>.done ("rc=<n> <run dir>") when the fit process exits.

usage: run_smoke_B.py [--arm B] [--steps 20] [--tag smokeB]
Credits: the 0813 harness jobs/fit_band0813.ps1 (spiral-patches-ab) for the environment recipe.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('C:/VesuviusTemp/nov_strips')
VILLA_SF = Path('C:/VesuviusTemp/nov_snap/villa_main/spiral-fitting')
PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arm', default='B')
    ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--tag', default=None)
    ap.add_argument('--threads', type=int, default=2)
    ap.add_argument('--set', action='append', default=[], metavar='KEY=JSON',
                    help='extra config override for the smoke only (e.g. loss_weight_dense_spacing=0)')
    a = ap.parse_args()
    tag = a.tag or f'smoke{a.arm}'
    cfg = json.loads((ROOT / 'configs' / f'config_{a.arm}.json').read_text())
    cfg['optimizer_num_training_steps'] = a.steps
    for item in a.set:
        key, _, value = item.partition('=')
        cfg[key] = json.loads(value)
    sys.path.insert(0, str(VILLA_SF))
    from config import Config
    Config(cfg)
    for d in ('out', 'cache/spiral', 'tmp', 'logs'):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        'CUDA_VISIBLE_DEVICES': '-1', 'FIT_SPIRAL_DEVICE': 'cpu',
        'FIT_SPIRAL_CONFIG_OVERRIDES': json.dumps(cfg, separators=(',', ':'), sort_keys=True),
        'FIT_SPIRAL_OUT_DIR': str(ROOT / 'out'), 'FIT_SPIRAL_CACHE_DIR': str(ROOT / 'cache' / 'spiral'),
        'FIT_SPIRAL_RUN_TAG': tag, 'WANDB_MODE': 'disabled',
        'FIT_SPIRAL_PATCH_LOAD_WORKERS': '1', 'FIT_SPIRAL_PATCH_LOAD_IO_THREADS': '2',
        'OMP_NUM_THREADS': str(a.threads), 'MKL_NUM_THREADS': str(a.threads), 'TORCH_NUM_THREADS': str(a.threads),
        'PYTHONPATH': str(ROOT / 'villa_extra'), 'KMP_DUPLICATE_LIB_OK': 'TRUE', 'PYTHONIOENCODING': 'utf-8',
        'PYTHONUNBUFFERED': '1', 'TMP': str(ROOT / 'tmp'), 'TEMP': str(ROOT / 'tmp'),
    })
    manifest = {'tag': tag, 'arm': a.arm, 'steps': a.steps, 'config': cfg, 'villa': str(VILLA_SF),
                'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'threads': a.threads}
    (ROOT / 'logs' / f'fit_{tag}.manifest.json').write_text(json.dumps(manifest, indent=1))
    t0 = time.time()
    # fit_spiral_cpu.py = villa's fit_spiral.py with villa_extra (vc3d_fiber_format, vc_spiral natives) first on sys.path
    cmd = [PY, '-u', str(ROOT / 'fit_spiral_cpu.py'), '--dataset', str(ROOT / 'dataset')]
    print(' '.join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(VILLA_SF), env=env)
    runs = sorted(glob.glob(str(ROOT / 'out' / f'*{tag}*')), key=os.path.getmtime)
    run_dir = runs[-1] if runs else ''
    (ROOT / 'logs' / f'smoke_{a.arm}.done').write_text(f'rc={rc} {run_dir} seconds={time.time() - t0:.0f}\n')
    print(f'FIT_DONE {tag} rc={rc} {run_dir} seconds={time.time() - t0:.0f}', flush=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
