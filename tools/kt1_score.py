"""KT1 scorer: measures 1-4 of KT1_SCORING_RULES.md on the band strips.

Measures 1-2 reuse the frozen October scorer's functions unchanged (imported, never edited). Measures 3-4 and the
unconditional M7 read the November patches from a converted folder. Writes score/kt1_report.json. CPU only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import tifffile
from scipy.spatial import cKDTree

ROOT = Path('C:/VesuviusTemp/nov_strips')
SCORE = Path('C:/VesuviusTemp/strips/score')
OUT = ROOT / 'score'
SEGS = OUT / 'segments_masked'
BAND_L2 = (3200, 4200)
QUAD_SV2 = 20.0
UM = 9.596
PITCH_SV = 12.0
MIN_NODES = 25


def cm2(sv2):
    return sv2 * (UM * 1e-4) ** 2


def frozen_measures(strips_dir):
    sys.path.insert(0, str(SCORE))
    import score_strips as ss
    matches = json.loads((OUT / 'matched_band.json').read_text())
    stretches = matches['stretches']
    for n, st in enumerate(stretches):
        st['_n'] = n
    names = {st['fiber'] for st in stretches}
    fibers, _ = ss.load_fibers(str(SCORE / 'data/fibers0139'), 1., 'controlled', None, names=names)
    segs = ss.discover_segments([str(SEGS)], None, 1.)
    if [s.name for s in segs] != [s['name'] for s in matches['segments']]:
        raise SystemExit('segments differ from the matches file')
    strips = [ss.load_strip(d, 4.) for d in ss.discover_strips(str(strips_dir))]

    class A:  # load_axis reads these fields only
        umbilicus = str(SCORE / 'data/umbilicus/PHerc0139_20260102150214_umbilicus.json')
        umbilicus_unit_base = 1.
    axis = ss.load_axis(A)
    entries, skips = ss.score_strips(strips, fibers, stretches, segs, axis, None, pieces=matches.get('pieces', []))
    acc = {fam or 'all': ss.aggregate(entries, fam) for fam in (None, 'H', 'V')}
    rows, short = [], 0
    for e in entries.values():
        err = np.abs(e['err']['strip'])
        err = err[np.isfinite(err)]
        if err.size < MIN_NODES:
            short += 1
            continue
        rows.append({'strip': e['strip'], 'fiber': e['fiber'], 'family': e['family'], 'nodes': int(err.size),
                     'median_abs_sv': float(np.median(err)), 'within2': float((err <= 2).mean())})
    off = sum(r['median_abs_sv'] > 6 for r in rows)
    return {'stretches': len(stretches), 'strips_loaded': len(strips), 'skips': len(skips), 'accuracy': ss.jsonable(acc),
            'per_strip': rows, 'strips_scored': len(rows), 'strips_too_few_nodes': short,
            'off_sheet_strips': int(off), 'off_sheet_share': off / max(len(rows), 1)}


def load_grid(d):
    grid = np.stack([tifffile.imread(Path(d) / f'{c}.tif').astype(np.float64) for c in 'xyz'], -1)
    return grid, np.isfinite(grid).all(-1) & ~(grid == -1).any(-1)


def wrap_nodes():
    """Per wrap: valid nodes (L2 sv) and unit normals from the grid."""
    pts, nrm, wid = [], [], []
    names = []
    for k, d in enumerate(sorted(p for p in SEGS.iterdir() if (p / 'x.tif').exists())):
        grid, valid = load_grid(d)
        g = grid / 4.0
        du = np.gradient(g, axis=0)
        dv = np.gradient(g, axis=1)
        n = np.cross(du, dv)
        ln = np.linalg.norm(n, axis=-1)
        ok = valid & np.isfinite(ln) & (ln > 0)
        pts.append(g[ok])
        nrm.append(n[ok] / ln[ok][:, None])
        wid.append(np.full(int(ok.sum()), k))
        names.append(re.search(r'-(w\d{3})_', d.name).group(1))
    return np.concatenate(pts), np.concatenate(nrm), np.concatenate(wid), names


def patch_measures(patch_dir):
    P, N, W, names = wrap_nodes()
    tree = cKDTree(P)
    all_nodes, fam_nodes, area_sv2 = [], [], 0.0
    n_patches = 0
    for d in sorted(p for p in Path(patch_dir).iterdir() if (p / 'x.tif').exists()):
        grid, valid = load_grid(d)
        in_band = valid & (grid[..., 2] >= BAND_L2[0]) & (grid[..., 2] < BAND_L2[1])
        quad = in_band[:-1, :-1] & in_band[1:, :-1] & in_band[:-1, 1:] & in_band[1:, 1:]
        area_sv2 += float(quad.sum()) * QUAD_SV2
        if in_band.any():
            n_patches += 1
            all_nodes.append(grid[in_band])
            fam_nodes.append(np.full(int(in_band.sum()), n_patches))
    Q = np.concatenate(all_nodes)
    dist, idx = tree.query(Q, k=1, workers=2)
    # normal offset to the nearest wrap node's tangent plane; lateral part must stay within the 5 sv wrap grid
    d_vec = Q - P[idx]
    normal = np.abs((d_vec * N[idx]).sum(1))
    lateral = np.sqrt(np.maximum(dist ** 2 - normal ** 2, 0))
    has_wrap = lateral <= 5.0
    within2 = float((normal[has_wrap] <= 2).mean()) if has_wrap.any() else None
    # coverage: strict (same wrap, within half a pitch along the normal) and loose (any patch node within 30 sv)
    on_sheet = has_wrap & (normal <= PITCH_SV / 2)
    covered = np.zeros(len(P), bool)
    for k in range(len(names)):
        sel = np.flatnonzero(W == k)
        q = Q[on_sheet & (W[idx] == k)]
        if q.size and sel.size:
            dd, _ = cKDTree(q).query(P[sel], k=1, distance_upper_bound=30.0, workers=2)
            covered[sel] = np.isfinite(dd)
    dd, _ = cKDTree(Q).query(P, k=1, distance_upper_bound=30.0, workers=2)
    return {'patches_in_band': n_patches, 'area_in_band_cm2': cm2(area_sv2), 'patch_nodes': int(len(Q)),
            'unconditional_within2': within2, 'unconditional_nodes_with_wrap': int(has_wrap.sum()),
            'unconditional_chance_within2': 2 * 2 / PITCH_SV,
            'coverage_strict': float(covered.mean()), 'coverage_loose_3d': float(np.isfinite(dd).mean()),
            'wrap_nodes': int(len(P)),
            'coverage_strict_per_wrap': {names[k]: float(covered[W == k].mean()) for k in range(len(names))}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--strips', default=str(ROOT / 'infer/strips'))
    ap.add_argument('--patches', default=str(ROOT / 'patches/november_band'))
    ap.add_argument('--out', default=str(OUT / 'kt1_report.json'))
    args = ap.parse_args()
    fm = frozen_measures(args.strips)
    pm = patch_measures(args.patches)
    point = fm['accuracy']['all']['strip']['point']
    within2 = point.get('within2')
    bars = {'m7_within2_ge_70pct': within2 is not None and within2 >= 0.70,
            'm7_off_sheet_le_15pct': fm['off_sheet_share'] <= 0.15,
            'area_ge_3cm2': pm['area_in_band_cm2'] >= 3.0,
            'coverage_strict_ge_20pct': pm['coverage_strict'] >= 0.20}
    report = {'bars': bars, 'all_bars': all(bars.values()), 'within2': within2,
              'off_sheet_share': fm['off_sheet_share'], 'frozen': fm, 'patches': pm}
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ('bars', 'all_bars', 'within2', 'off_sheet_share')}, indent=1))
    print(json.dumps({k: v for k, v in pm.items() if k != 'coverage_strict_per_wrap'}, indent=1))
    print(json.dumps(fm['accuracy']['all']['strip']['point'], indent=1))


if __name__ == '__main__':
    main()
