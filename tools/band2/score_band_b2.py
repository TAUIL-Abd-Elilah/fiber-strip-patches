"""Band 2 copy (PREREG amendment 2: L2 z 4400-5400). Score the PHerc 0139 band fit A/B on CPU against the held-out human wraps (PREREG.md section 4).

Geometry and most metrics reuse spiral-patches-ab/score_ab.py (imported unchanged). New here: wraps as the held-out set
(L0 tifxyz divided by 4 into the L2 fit frame), one KD-tree per arm, adjacent-pair exactness (M3), and M1 split by
whether a wrap node is covered by a strip patch.

usage: score_band.py --arm A=<meshes dir> --arm B=<meshes dir> --out <json> [--sections 3400,3700,4000] [--boot 10000]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path('C:/VesuviusTemp/nov_strips')
SEGS = ROOT / 'stage2' / '0139' / 'score' / 'band01' / 'segments_masked'
PATCHES = ROOT / 'dataset_b2' / 'verified_patches'
HERE = Path(__file__).resolve().parent
for cand in (HERE, Path('D:/Competition/Vesuvius progress prizes/_public/spiral-patches-ab')):
    if (cand / 'score_ab.py').exists():
        sys.path.insert(0, str(cand))
        break
import score_ab as sa  # noqa: E402

UM = 9.596
Z0, Z1, EDGE = 4400, 5400, 20
CT = ('https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/'
      '20260102150214-2.399um-0.2m-78keV-masked.zarr')
GO_POINTS, GO_DUP_POINTS = 5.0, 1.0
PITCH_SV = 12.0


def load_wraps():
    """wNNN -> (zyx grid in L2, valid)."""
    out = {}
    for d in sorted(p for p in SEGS.iterdir() if (p / 'x.tif').exists()):
        wid = re.search(r'-(w\d{3})_', d.name).group(1)
        zyx, valid = sa.load_tifxyz(str(d))
        zyx = np.where(valid[..., None], zyx / 4.0, -1.0)
        out[wid] = (zyx, valid)
    return dict(sorted(out.items()))


def grid_normals(zyx, valid):
    du, dv = np.gradient(zyx, axis=0), np.gradient(zyx, axis=1)
    n = np.cross(du, dv)
    ln = np.linalg.norm(n, axis=-1)
    ok = valid & np.isfinite(ln) & (ln > 0)
    return n / np.where(ln > 0, ln, 1)[..., None], ok


def covered_masks(wraps):
    """Per wrap, nodes with a patch node within 30 sv that has this wrap as its nearest wrap and lies within half a
    pitch along the wrap's normal: the strict coverage rule of KT1_SCORING_RULES.md, measure 4. Cached."""
    cache = ROOT / 'score' / 'covered_masks_b2.npz'
    if cache.exists():
        z = np.load(cache)
        return {k: z[k] for k in z.files}
    pts, nrm, wid = [], [], []
    names = list(wraps)
    for k, w in enumerate(names):
        zyx, valid = wraps[w]
        n, ok = grid_normals(zyx, valid)
        pts.append(zyx[ok]), nrm.append(n[ok]), wid.append(np.full(int(ok.sum()), k))
    P, N, W = np.concatenate(pts), np.concatenate(nrm), np.concatenate(wid)
    tree = cKDTree(P)
    Q = []
    for d in sorted(p for p in PATCHES.iterdir() if (p / 'x.tif').exists()):
        zyx, valid = sa.load_tifxyz(str(d))
        keep = valid & (zyx[..., 0] >= Z0) & (zyx[..., 0] < Z1)
        Q.append(zyx[keep])
    Q = np.concatenate(Q)
    dist, idx = tree.query(Q, k=1, workers=2)
    normal = np.abs(((Q - P[idx]) * N[idx]).sum(1))
    lateral = np.sqrt(np.maximum(dist ** 2 - normal ** 2, 0))
    on = (lateral <= 5.0) & (normal <= PITCH_SV / 2)
    out = {}
    for k, w in enumerate(names):
        zyx, valid = wraps[w]
        mask = np.zeros(valid.shape, bool)
        q = Q[on & (W[idx] == k)]
        if q.size:
            dd, _ = cKDTree(q).query(zyx[valid], k=1, distance_upper_bound=30.0, workers=2)
            mask[valid] = np.isfinite(dd)
        out[w] = mask
    np.savez_compressed(cache, **out)
    return out


class Mesh:
    def __init__(self, windings, max_dist=4.0, radius_cap=60.0):
        tris, wid, centres, radii = sa.mesh_triangles(windings)
        keep = radii <= radius_cap
        self.dropped = int((~keep).sum() // 2)
        self.tris, self.wid = tris[keep], wid[keep]
        self.tree = cKDTree(centres[keep])
        self.reach = max_dist + float(radii[keep].max())
        self.max_dist = max_dist

    def query(self, points, chunk=20000):
        dist = np.full(len(points), np.inf)
        win = np.full(len(points), -1)
        for s in range(0, len(points), chunk):
            p = points[s:s + chunk]
            lists = self.tree.query_ball_point(p, self.reach, workers=2)
            pi = np.repeat(np.arange(len(p)), [len(l) for l in lists])
            if not len(pi):
                continue
            ti = np.fromiter((j for l in lists for j in l), dtype=np.int64, count=len(pi))
            d = sa.point_triangle_distance(p[pi], self.tris[ti, 0], self.tris[ti, 1], self.tris[ti, 2])
            order = np.lexsort((d, pi))
            pi, ti, d = pi[order], ti[order], d[order]
            first = np.r_[0, np.flatnonzero(np.diff(pi)) + 1]
            best = d[first] <= self.max_dist
            dist[s + pi[first][best]] = d[first][best]
            win[s + pi[first][best]] = self.wid[ti[first][best]]
        return dist, win


def score_arm(windings, wraps, covered):
    mesh = Mesh(windings)
    rows, grids = {}, {}
    for w, (zyx, valid) in wraps.items():
        inwin = valid & (zyx[..., 0] >= Z0 + EDGE) & (zyx[..., 0] < Z1 - EDGE)
        pts = zyx[inwin]
        dist, win = mesh.query(pts)
        grid_w = np.full(valid.shape, -1)
        grid_w[inwin] = win
        grids[w] = grid_w
        hops = 0
        for a, b in ((grid_w[:, :-1], grid_w[:, 1:]), (grid_w[:-1, :], grid_w[1:, :])):
            both = (a >= 0) & (b >= 0)
            hops += int((both & (a != b)).sum())
        matched = win[win >= 0]
        ids, counts = np.unique(matched, return_counts=True) if len(matched) else (np.array([]), np.array([]))
        cov = covered[w][inwin]
        rows[w] = dict(nodes=int(len(pts)), within_2=int((dist <= 2).sum()), within_4=int((dist <= 4).sum()),
                       winding_hops=hops, distinct_windings=int(len(ids)),
                       modal_share=float(counts.max() / len(matched)) if len(matched) else 0.0,
                       covered_nodes=int(cov.sum()), covered_within_2=int((dist[cov] <= 2).sum()),
                       uncovered_nodes=int((~cov).sum()), uncovered_within_2=int((dist[~cov] <= 2).sum()))
    return rows, grids, mesh.dropped


def adjacent_pairs(wraps, grids):
    """M3. For each adjacent wrap pair, at nodes of the inner wrap matched to a winding, take the outer wrap's nearest
    matched node within 30 sv: exact when the two windings differ by the arm's dominant step (+1 or -1)."""
    names = list(wraps)
    pairs = {}
    diffs = []
    for a, b in zip(names, names[1:]):
        if int(b[1:]) != int(a[1:]) + 1:
            continue
        ga, gb = grids[a], grids[b]
        ma, mb = ga >= 0, gb >= 0
        if not ma.any() or not mb.any():
            continue
        pa = wraps[a][0][ma][::4]
        wa = ga[ma][::4]
        dd, idx = cKDTree(wraps[b][0][mb]).query(pa, k=1, distance_upper_bound=30.0, workers=2)
        ok = np.isfinite(dd)
        d = gb[mb][idx[ok]] - wa[ok]
        pairs[f'{a}-{b}'] = d
        diffs.append(d)
    all_d = np.concatenate(diffs) if diffs else np.zeros(0, int)
    step = 1 if (all_d == 1).sum() >= (all_d == -1).sum() else -1
    per = {k: dict(samples=int(len(v)), exact=int((v == step).sum()), same_winding=int((v == 0).sum()))
           for k, v in pairs.items()}
    tot = sum(r['samples'] for r in per.values())
    return dict(step=step, samples=tot, exact_share=sum(r['exact'] for r in per.values()) / max(tot, 1),
                same_winding_share=sum(r['same_winding'] for r in per.values()) / max(tot, 1), per_pair=per)


def pair_bootstrap(rows_a, rows_b, key, boot, seed):
    return sa.paired_bootstrap(rows_a, rows_b, key, boot, seed)


def sections(windings_by_arm, wraps, zs, prefix):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import zarr
    store = zarr.storage.FsspecStore.from_url(CT.rstrip('/') + '/2', read_only=True)
    arr = zarr.open_array(store, mode='r', zarr_format=2)
    allp = np.concatenate([zyx[v][::50] for zyx, v in wraps.values()])
    y0, x0 = int(allp[:, 1].min()) - 60, int(allp[:, 2].min()) - 60
    y1, x1 = int(allp[:, 1].max()) + 60, int(allp[:, 2].max()) + 60
    out = []
    for z in zs:
        img = np.asarray(arr[z, y0:y1, x0:x1])
        fig, ax = plt.subplots(figsize=(14, 14 * (y1 - y0) / max(x1 - x0, 1)))
        ax.imshow(img, cmap='gray', extent=(x0, x1, y1, y0))
        for (arm, windings), colour in zip(windings_by_arm.items(), ('tab:orange', 'tab:cyan')):
            for _, _, zyx, v in windings:
                s = sa.plane_cut(zyx, v, z)
                if len(s):
                    ax.plot(s[:, :, 1].T, s[:, :, 0].T, color=colour, lw=0.4)
            ax.plot([], [], color=colour, label=f'arm {arm}')
        for w, (zyx, v) in wraps.items():
            s = sa.plane_cut(zyx, v, z)
            if len(s):
                ax.plot(s[:, :, 1].T, s[:, :, 0].T, color='magenta', lw=0.4)
        ax.plot([], [], color='magenta', label='held-out wraps')
        ax.set_xlim(x0, x1), ax.set_ylim(y1, y0), ax.set_title(f'L2 z = {z}'), ax.legend(loc='upper right')
        path = f'{prefix}_z{z}.png'
        fig.savefig(path, dpi=200, bbox_inches='tight')
        plt.close(fig)
        out.append(path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arm', action='append', required=True, metavar='NAME=MESHES_DIR')
    ap.add_argument('--out', required=True)
    ap.add_argument('--sections', default='')
    ap.add_argument('--boot', type=int, default=10000)
    ap.add_argument('--seed', type=int, default=12345)
    a = ap.parse_args()
    wraps = load_wraps()
    covered = covered_masks(wraps)
    result = {'wraps': list(wraps), 'z_window': [Z0 + EDGE, Z1 - EDGE], 'arms': {}}
    by_arm = {}
    for arm, d in sa.kv(a.arm).items():
        windings = sa.load_windings(d)
        by_arm[arm] = windings
        rows, grids, dropped = score_arm(windings, wraps, covered)
        n = sum(r['nodes'] for r in rows.values())
        cn = sum(r['covered_nodes'] for r in rows.values())
        un = sum(r['uncovered_nodes'] for r in rows.values())
        res = dict(meshes=d, windings=len(windings), nodes=n, quads_over_radius_cap=dropped,
                   within_2=sum(r['within_2'] for r in rows.values()) / max(n, 1),
                   within_4=sum(r['within_4'] for r in rows.values()) / max(n, 1),
                   covered_share=cn / max(n, 1),
                   within_2_covered=sum(r['covered_within_2'] for r in rows.values()) / max(cn, 1),
                   within_2_uncovered=sum(r['uncovered_within_2'] for r in rows.values()) / max(un, 1),
                   winding_hops_total=int(sum(r['winding_hops'] for r in rows.values())),
                   adjacent_pairs=adjacent_pairs(wraps, grids),
                   duplicate_sheet=sa.duplicate_sheet_share(windings, UM), per_wrap=rows)
        result['arms'][arm] = res
        print(f"arm {arm}: {len(windings)} windings; within 2 {res['within_2']:.1%}, within 4 {res['within_4']:.1%}; "
              f"covered {res['within_2_covered']:.1%} ({res['covered_share']:.1%} of nodes), "
              f"uncovered {res['within_2_uncovered']:.1%}; adjacent exact {res['adjacent_pairs']['exact_share']:.1%}; "
              f"hops {res['winding_hops_total']}; duplicate {res['duplicate_sheet']['shared_share']:.1%}", flush=True)
    if {'A', 'B'} <= set(result['arms']):
        ra, rb = result['arms']['A']['per_wrap'], result['arms']['B']['per_wrap']
        cmp_ = {k: sa.paired_bootstrap(ra, rb, k, a.boot, a.seed) for k in ('within_2', 'within_4')}
        dup = result['arms']['B']['duplicate_sheet']['shared_share'] - result['arms']['A']['duplicate_sheet']['shared_share']
        w2 = cmp_['within_2']
        cmp_['duplicate_sheet_share_B_minus_A'] = dup
        cmp_['adjacent_exact_B_minus_A'] = (result['arms']['B']['adjacent_pairs']['exact_share']
                                            - result['arms']['A']['adjacent_pairs']['exact_share'])
        cmp_['GO'] = bool(w2['point'] * 100 >= GO_POINTS and w2['ci95'][0] > 0 and dup * 100 <= GO_DUP_POINTS)
        cmp_['go_rule'] = f'B-A M1 >= +{GO_POINTS:g} points, 95% CI above 0, duplicate share B-A <= +{GO_DUP_POINTS:g} points'
        result['B_minus_A'] = cmp_
        print(f"B-A within 2 {w2['point'] * 100:+.1f} points (CI {w2['ci95'][0] * 100:+.1f} to {w2['ci95'][1] * 100:+.1f}); "
              f"duplicate {dup * 100:+.1f} -> {'GO' if cmp_['GO'] else 'NO-GO'}", flush=True)
    if a.sections:
        result['sections'] = sections(by_arm, wraps, [int(z) for z in a.sections.split(',')],
                                      os.path.splitext(a.out)[0])
    Path(a.out).write_text(json.dumps(result, indent=1, default=float))


if __name__ == '__main__':
    main()
