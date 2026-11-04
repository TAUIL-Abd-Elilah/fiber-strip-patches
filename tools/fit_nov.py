"""fit_nov.py <A|B> <seed> [--dry]: one 20,000-step fit of the PHerc 0139 band A/B (PREREG.md) on the GPU. No PowerShell.

Environment after First Letters' fit_direct.py. Refuses to start beside another fit_spiral.py, if its .done already exists,
or if the fit would leave C: under 30 GB. Writes logs/fit_<tag>.done ("rc=<n> <run dir> seconds=<s>") also on a crash.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path('C:/VesuviusTemp/nov_strips')
PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'
VILLA_SF = 'C:/VesuviusTemp/nov_snap/villa_main/spiral-fitting'
MEM_FRACTION = '0.82'
FIT_PEAK_GB = 3
C_FLOOR_GB = 30


def fits_running():
    out = []
    for p in psutil.process_iter():
        try:
            if p.name().lower() == 'python.exe' and any('fit_spiral.py' in c for c in p.cmdline()):
                out.append(p.pid)
        except (psutil.Error, OSError):
            pass
    return out


def main():
    arm, seed = sys.argv[1], int(sys.argv[2])
    dry = '--dry' in sys.argv
    if arm not in ('A', 'B') or seed not in (1, 2):
        raise SystemExit('usage: fit_nov.py <A|B> <1|2> [--dry]')
    tag = f'nov{arm}{seed}'
    done = ROOT / 'logs' / f'fit_{tag}.done'
    log = ROOT / 'logs' / f'fit_{tag}.log'
    t0 = time.time()

    def finish(rc, run_dir=''):
        done.write_text(f'rc={rc} {run_dir} seconds={time.time() - t0:.0f}\n')
        print(f'FIT_DONE {tag} rc={rc} {run_dir} seconds={time.time() - t0:.0f}', flush=True)
        return rc

    name = f'config_{arm}.json' if seed == 1 else f'config_{arm}_seed{seed}.json'
    cfg = json.loads((ROOT / 'configs' / name).read_text())
    n_patches = sum(1 for p in (ROOT / 'dataset/verified_patches').iterdir() if (p / 'x.tif').exists())
    free = shutil.disk_usage('C:/').free / 2 ** 30
    print(f'{tag}: config {name}, seed {cfg["optimizer_random_seed"]}, disable_patches {cfg["input_disable_patches"]}, '
          f'{n_patches} patches on disk, C: {free:.1f} GiB free, mem fraction {MEM_FRACTION}', flush=True)
    if dry:
        return 0
    if done.exists():
        print(f'{done} exists; not starting', flush=True)
        return 3
    if fits_running():
        return finish(4)
    if free - FIT_PEAK_GB < C_FLOOR_GB:
        print(f'C: {free:.1f} GiB free; would fall under {C_FLOOR_GB} GB', flush=True)
        return finish(5)
    env = dict(os.environ)
    for k in ('CUDA_VISIBLE_DEVICES', 'FIT_SPIRAL_DEVICE', 'FIT_SPIRAL_RESUME_PATH', 'FIT_SPIRAL_RESUME_STEP'):
        env.pop(k, None)
    for d in ('out', 'cache/spiral', 'cache/torchinductor', 'tmp', 'logs'):
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    env.update({
        'FIT_SPIRAL_CONFIG_OVERRIDES': json.dumps(cfg, separators=(',', ':'), sort_keys=True),
        'FIT_SPIRAL_OUT_DIR': str(ROOT / 'out'), 'FIT_SPIRAL_CACHE_DIR': str(ROOT / 'cache/spiral'),
        'FIT_SPIRAL_RUN_TAG': tag, 'FIT_SPIRAL_GPU_MEM_FRACTION': MEM_FRACTION, 'FIT_SPIRAL_CKPT_EVERY': '2000',
        'FIT_SPIRAL_PATCH_LOAD_WORKERS': '1', 'FIT_SPIRAL_PATCH_LOAD_IO_THREADS': '2',
        'TORCHINDUCTOR_CACHE_DIR': str(ROOT / 'cache/torchinductor'), 'WANDB_MODE': 'disabled',
        'PYTHONPATH': str(ROOT / 'villa_extra'), 'KMP_DUPLICATE_LIB_OK': 'TRUE', 'PYTHONIOENCODING': 'utf-8',
        'PYTHONUNBUFFERED': '1', 'TMP': str(ROOT / 'tmp'), 'TEMP': str(ROOT / 'tmp')})
    rc = 99
    try:
        with open(log, 'w', encoding='utf-8') as f:
            rc = subprocess.run([PY, '-u', str(ROOT / 'fit_wrap/fit_spiral.py'), '--dataset', str(ROOT / 'dataset')],
                                cwd=VILLA_SF, env=env, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW).returncode
    finally:
        runs = sorted(glob.glob(str(ROOT / 'out' / f'*{tag}*')), key=os.path.getmtime)
        finish(rc, runs[-1] if runs else '')
    return rc


if __name__ == '__main__':
    sys.exit(main())
