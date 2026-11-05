"""PREREG amendment 1: winding purity from the JSON that tools/score_band.py already writes. No geometry here.

Purity of a wrap = `modal_share`: of its nodes within 4 voxels of a fitted winding, the share on its most common winding.
B-A is the mean over wraps, with a paired bootstrap by wrap (same seed and replicates as score_band.py).

usage: score_purity.py <scored.json> [--noise <other seed's scored.json>] [--boot 10000] [--seed 12345]
"""
import argparse
import json

import numpy as np

BAR_POINTS, MID_POINTS = 5.0, 2.0
M1_FLOOR, M3_FLOOR, M4_CAP, SAME_CAP = -1.0, -1.0, 1.0, 1.0


def purity(arm):
    rows = arm['per_wrap']
    return {w: rows[w]['modal_share'] for w in rows}


def paired(a, b, boot, seed):
    wraps = sorted(a)
    d = np.array([b[w] - a[w] for w in wraps])
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, len(d), (boot, len(d)))].mean(1)
    return dict(point=float(d.mean()), ci95=[float(x) for x in np.percentile(means, [2.5, 97.5])],
                wraps=len(wraps), wraps_up=int((d > 0).sum()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scored')
    ap.add_argument('--noise')
    ap.add_argument('--boot', type=int, default=10000)
    ap.add_argument('--seed', type=int, default=12345)
    a = ap.parse_args()
    r = json.load(open(a.scored, encoding='utf-8'))
    A, B = r['arms']['A'], r['arms']['B']
    p = paired(purity(A), purity(B), a.boot, a.seed)
    pts, lo = p['point'] * 100, p['ci95'][0] * 100
    ba = r['B_minus_A']
    guards = dict(M1=ba['within_2']['point'] * 100, M3=ba['adjacent_exact_B_minus_A'] * 100,
                  M4=ba['duplicate_sheet_share_B_minus_A'] * 100,
                  same_winding=(B['adjacent_pairs']['same_winding_share'] - A['adjacent_pairs']['same_winding_share']) * 100)
    ok = guards['M1'] >= M1_FLOOR and guards['M3'] >= M3_FLOOR and guards['M4'] <= M4_CAP and guards['same_winding'] <= SAME_CAP
    out = dict(B_minus_A_purity_points=pts, ci95_points=[x * 100 for x in p['ci95']], wraps=p['wraps'], wraps_up=p['wraps_up'],
               purity_A=float(np.mean(list(purity(A).values()))) * 100, purity_B=float(np.mean(list(purity(B).values()))) * 100,
               guards_points=guards, guards_ok=ok)
    noise_ok = None
    if a.noise:
        o = json.load(open(a.noise, encoding='utf-8'))
        n = paired(purity(o['arms']['A']), purity(A), a.boot, a.seed)
        out['A_seed_noise_points'] = n['point'] * 100
        out['A_seed_noise_ci95_points'] = [x * 100 for x in n['ci95']]
        noise_ok = abs(n['point'] * 100) < pts / 2
        out['noise_ok'] = noise_ok
    if pts >= BAR_POINTS and lo > 0 and ok and noise_ok is not False:
        out['decision'] = 'confirmed' if a.noise else 'bar met, no seed-noise check in this run'
    elif pts >= MID_POINTS and lo > 0 and ok and noise_ok is not False:
        out['decision'] = 'smaller, below the bar'
    else:
        out['decision'] = 'not confirmed'
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
