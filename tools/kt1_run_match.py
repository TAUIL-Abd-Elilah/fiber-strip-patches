"""Frozen October `match` over all 0139 fibers against the masked band wraps. Looks at fibers and wraps only, no strip.
Started detached; writes score/match_band.done with the return code, also on failure."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path('C:/VesuviusTemp/nov_strips')
SCORE = Path('C:/VesuviusTemp/strips/score')
OUT = ROOT / 'score'
PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'
cmd = [PY, '-I', '-B', '-u', str(SCORE / 'score_strips.py'), 'match',
       '--fibers', str(SCORE / 'data/fibers0139'), '--space', 'PHerc0139/20260102150214@L0',
       '--segments', str(OUT / 'segments_masked'),
       '--umbilicus', str(SCORE / 'data/umbilicus/PHerc0139_20260102150214_umbilicus.json'),
       '--ct-zarray', 'https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/'
                      '20260102150214-2.399um-0.2m-78keV-masked.zarr/2',
       '--ct-cache', 'C:/VesuviusTemp/strips/ct_cache', '--workers', '3', '--tmpdir', str(OUT / 'match_tmp'),
       '--min-stretch-mm', '0.38384', '--analysis', 'secondary',
       '--full-run-map', str(SCORE / 'data/full_run_map_0139.npz'), '--out', str(OUT / 'matched_band.json')]
env = dict(os.environ, CUDA_VISIBLE_DEVICES='-1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
           PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
(OUT / 'match_tmp').mkdir(parents=True, exist_ok=True)
rc = 99
try:
    with open(OUT / 'match_band.log', 'w', encoding='utf-8') as log:
        log.write(' '.join(cmd) + '\n')
        log.flush()
        rc = subprocess.run(cmd, cwd=str(SCORE), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW).returncode
finally:
    (OUT / 'match_band.done').write_text(f'rc={rc}\n')
sys.exit(rc)
