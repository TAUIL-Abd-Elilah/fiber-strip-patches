"""Score one finished PHerc 0139 stage-2 band against the wraps with the KT1 rules, without touching the frozen A/B files.

usage: score_band_window.py <bandNN> <z0> <z1> [flagged piece ...]
Masks are rebuilt for this window (same rules as kt1_masks.py, full umbilicus). Runs the frozen October match and scorer.
Outputs under stage2/0139/score/<bandNN>/. CPU only, <= 4 threads.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path('C:/VesuviusTemp/nov_strips')
sys.path.insert(0, str(ROOT))
os.environ.update(CUDA_VISIBLE_DEVICES='-1', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', PYTHONDONTWRITEBYTECODE='1')
import numpy as np  # noqa: E402

import kt1_masks as km  # noqa: E402
import kt1_score as ks  # noqa: E402

band, z0, z1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
flagged = sys.argv[4:]
OUT = ROOT / 'stage2/0139/score' / band
SCORE = ks.SCORE
(OUT / 'score').mkdir(parents=True, exist_ok=True)
km.ROOT = OUT
km.DST = OUT / 'segments_masked'
km.UMB = Path('C:/VesuviusTemp/strips/data/umbilicus/PHerc0139_20260102150214_umbilicus_L2.json')
km.Z0, km.Z1 = z0 * km.L0_PER_SV, z1 * km.L0_PER_SV
km.main()

PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'
matches = OUT / 'matched.json'
cmd = [PY, '-I', '-B', '-u', str(SCORE / 'score_strips.py'), 'match', '--fibers', str(SCORE / 'data/fibers0139'),
       '--space', 'PHerc0139/20260102150214@L0', '--segments', str(km.DST),
       '--umbilicus', str(SCORE / 'data/umbilicus/PHerc0139_20260102150214_umbilicus.json'),
       '--ct-zarray', 'https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/'
                      '20260102150214-2.399um-0.2m-78keV-masked.zarr/2',
       '--ct-cache', 'C:/VesuviusTemp/strips/ct_cache', '--workers', '3', '--tmpdir', str(OUT / 'match_tmp'),
       '--min-stretch-mm', '0.38384', '--analysis', 'secondary',
       '--full-run-map', str(SCORE / 'data/full_run_map_0139.npz'), '--out', str(matches)]
(OUT / 'match_tmp').mkdir(exist_ok=True)
with open(OUT / 'match.log', 'w', encoding='utf-8') as log:
    rc = subprocess.run(cmd, cwd=str(SCORE), env=dict(os.environ, PYTHONIOENCODING='utf-8'), stdin=subprocess.DEVNULL,
                        stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW).returncode
print('match rc', rc, flush=True)
if rc:
    sys.exit(rc)

m = json.loads(matches.read_text())
(OUT / 'matched_band.json').write_text(json.dumps(m))
ks.OUT, ks.SEGS, ks.BAND_L2 = OUT, km.DST, (z0, z1)
bd = ROOT / 'stage2/0139' / band
fm = ks.frozen_measures(bd / 'strips')
pm = ks.patch_measures(bd / 'patches')
point = fm['accuracy']['all']['strip']
fam = {k: fm['accuracy'][k]['strip']['point'].get('within2') for k in ('H', 'V')}
fibers = {k: fm['accuracy'][k]['strip'].get('fibers') for k in ('H', 'V')}
report = dict(band=band, z=[z0, z1], stretches=fm['stretches'], fibers_scored=point.get('fibers'), strips_scored=fm['strips_scored'],
              within2=point['point']['within2'], within2_ci=(point.get('ci') or {}).get('within2'), within2_family=fam, fibers_family=fibers,
              off_sheet_share=fm['off_sheet_share'], off_sheet_strips=fm['off_sheet_strips'],
              **{k: v for k, v in pm.items() if k != 'coverage_strict_per_wrap'}, frozen_per_strip=fm['per_strip'])
if flagged:
    rows = {r['strip']: r for r in fm['per_strip']}
    report['flagged'] = {f: rows.get(f, 'no matched stretch') for f in flagged}
(OUT / 'report.json').write_text(json.dumps(report, indent=1, default=float))
print(json.dumps({k: v for k, v in report.items() if k != 'frozen_per_strip'}, indent=1, default=float))
