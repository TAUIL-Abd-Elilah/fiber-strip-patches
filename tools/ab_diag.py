"""Post hoc diagnostic of the seed-1 A/B, not a PREREG metric. Asks why M1 did not move:

1. Is 31 % within 2 sv above chance? Wrap nodes shifted along their own normal give the empirical chance level.
2. Is the scorer's frame right? Human fibers are fit inputs lying on the sheet, so they must score far above chance.
3. Did arm B adopt its patches? Patch nodes against each arm.

Wraps are read only for scoring, as in score_band.py. Samples every 16th wrap node. CPU, 2 threads.
usage: ab_diag.py <A meshes> <B meshes> <out json>
"""
import glob
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('OMP_NUM_THREADS', '2')
import numpy as np  # noqa: E402

import score_band as sb  # noqa: E402

ROOT = Path('C:/VesuviusTemp/nov_strips')
STEP, SHIFTS, EDGES = 16, (0.0, 3.0, 6.0, -6.0), (1, 2, 3, 4, 6, 8)


def wrap_samples():
    pts, nrm, wid = [], [], []
    for w, (zyx, valid) in sb.load_wraps().items():
        n, ok = sb.grid_normals(zyx, valid)
        keep = ok & (zyx[..., 0] >= sb.Z0 + sb.EDGE) & (zyx[..., 0] < sb.Z1 - sb.EDGE)
        pts.append(zyx[keep][::STEP])
        nrm.append(n[keep][::STEP])
        wid += [w] * len(zyx[keep][::STEP])
    return np.concatenate(pts), np.concatenate(nrm), np.array(wid)


def fiber_samples():
    out = []
    for f in sorted(glob.glob(str(ROOT / 'dataset/fibers/*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        lp = d.get('line_points') or []
        p = [q['position'] if isinstance(q, dict) else q for q in lp] or [c['position'] for c in d['control_points']]
        p = np.asarray(p, float)[:, ::-1] / 4.0  # L0 xyz -> L2 zyx
        out.append(p[(p[:, 0] >= sb.Z0 + sb.EDGE) & (p[:, 0] < sb.Z1 - sb.EDGE)][::4])
    return np.concatenate(out)


def patch_samples():
    out = []
    for d in sorted(p for p in (ROOT / 'dataset/verified_patches').iterdir() if (p / 'x.tif').exists()):
        zyx, valid = sb.sa.load_tifxyz(str(d))
        keep = valid & (zyx[..., 0] >= sb.Z0 + sb.EDGE) & (zyx[..., 0] < sb.Z1 - sb.EDGE)
        out.append(zyx[keep][::8])
    return np.concatenate(out)


def shares(dist):
    return {f'within_{e}': float((dist <= e).mean()) for e in EDGES}


def main():
    arms, out_path = {'A': sys.argv[1], 'B': sys.argv[2]}, sys.argv[3]
    P, N, W = wrap_samples()
    F, Q = fiber_samples(), patch_samples()
    print('samples: wrap', len(P), 'fiber', len(F), 'patch', len(Q), flush=True)
    res = {'note': 'post hoc, not a PREREG metric', 'samples': dict(wrap=len(P), fiber=len(F), patch=len(Q)), 'arms': {}}
    for arm, d in arms.items():
        mesh = sb.Mesh(sb.sa.load_windings(d), max_dist=8.0)
        r = {}
        for s in SHIFTS:
            dist, _ = mesh.query(P + s * N)
            r[f'wrap_shift_{s:+g}'] = shares(dist)
            print(arm, f'wrap shift {s:+g}', {k: round(100 * v, 1) for k, v in shares(dist).items()}, flush=True)
        dist, _ = mesh.query(F)
        r['fiber'] = shares(dist)
        print(arm, 'fiber', {k: round(100 * v, 1) for k, v in shares(dist).items()}, flush=True)
        dist, _ = mesh.query(Q)
        r['patch'] = shares(dist)
        print(arm, 'patch', {k: round(100 * v, 1) for k, v in shares(dist).items()}, flush=True)
        res['arms'][arm] = r
        Path(out_path).write_text(json.dumps(res, indent=1))
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
