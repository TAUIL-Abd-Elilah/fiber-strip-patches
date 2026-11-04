"""KT1 diagnostics, reported only, written after the bars were scored (they change no bar).

Question: patch nodes sit within 2 sv of the nearest wrap at about the chance rate. Is that the strips, or the human
fibers, or the metric? Same metric as kt1_score.patch_measures on: (a) patch nodes, (b) the same nodes shifted radially
by half a pitch and a quarter pitch (empirical chance), (c) human fiber samples of the 144 band fibers, (d) wrap nodes
of one wrap against the others (positive control on spacing), split by H and V.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

import kt1_score as ks

ROOT = ks.ROOT
UMB = ROOT / 'dataset' / 'umbilicus.json'
BAND = ks.BAND_L2


def umb(z):
    pts = sorted(json.loads(UMB.read_text())['control_points'], key=lambda p: p['z'])
    zs = [p['z'] for p in pts]
    return np.stack([np.interp(z, zs, [p['x'] for p in pts]), np.interp(z, zs, [p['y'] for p in pts])], -1)


def metric(Q, tree, P, N):
    dist, idx = tree.query(Q, k=1, workers=2)
    d = Q - P[idx]
    normal = np.abs((d * N[idx]).sum(1))
    lateral = np.sqrt(np.maximum(dist ** 2 - normal ** 2, 0))
    has = lateral <= 5.0
    return {'nodes': int(len(Q)), 'with_wrap': int(has.sum()),
            'within2': float((normal[has] <= 2).mean()) if has.any() else None,
            'within4': float((normal[has] <= 4).mean()) if has.any() else None,
            'median_sv': float(np.median(normal[has])) if has.any() else None}


def radial_shift(Q, s):
    c = umb(Q[:, 2])
    v = Q[:, :2] - c
    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
    out = Q.copy()
    out[:, :2] += s * v
    return out


def main():
    P, N, W, names = ks.wrap_nodes()
    tree = cKDTree(P)
    report = {}
    fam = {}
    manifest = json.loads((ROOT / 'patches/november_band/manifest.json').read_text())
    fibers_dir = ROOT / 'dataset/fibers'
    nodes, fams = [], []
    for d in sorted(p for p in (ROOT / 'patches/november_band').iterdir() if (p / 'x.tif').exists()):
        grid, valid = ks.load_grid(d)
        keep = valid & (grid[..., 2] >= BAND[0]) & (grid[..., 2] < BAND[1])
        if keep.any():
            meta = json.loads((d / 'meta.json').read_text())
            f = (meta.get('provenance') or {}).get('family') or (meta.get('provenance') or {}).get('fiber', {}).get('family')
            nodes.append(grid[keep])
            fams.append(np.full(int(keep.sum()), 0 if f == 'H' else (1 if f == 'V' else 2)))
    Q = np.concatenate(nodes)
    F = np.concatenate(fams)
    report['patch_nodes'] = metric(Q, tree, P, N)
    report['patch_nodes_H'] = metric(Q[F == 0], tree, P, N) if (F == 0).any() else None
    report['patch_nodes_V'] = metric(Q[F == 1], tree, P, N) if (F == 1).any() else None
    for s in (3.0, 6.0, -3.0, -6.0):
        report[f'patch_nodes_shift_{s:+.0f}sv'] = metric(radial_shift(Q, s), tree, P, N)
    # human fibers: controlled span only (villa's rule), in band, L2 frame
    pts, famf = [], []
    for f in sorted(fibers_dir.glob('*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        line = np.asarray(d['line_points'], float).reshape(-1, 3) * 0.25
        keep = (line[:, 2] >= BAND[0]) & (line[:, 2] < BAND[1])
        if keep.any():
            pts.append(line[keep])
            hv = d.get('hv_classification') or {}
            tag = hv.get('manual_tag') or hv.get('automatic_tag') or '?'
            famf.append(np.full(int(keep.sum()), 0 if tag == 'H' else (1 if tag == 'V' else 2)))
    H = np.concatenate(pts)
    G = np.concatenate(famf)
    report['human_fibers'] = metric(H, tree, P, N)
    report['human_fibers_H'] = metric(H[G == 0], tree, P, N)
    report['human_fibers_V'] = metric(H[G == 1], tree, P, N)
    # spacing between adjacent wraps, for the chance level: nearest other-wrap distance along the normal
    rng = np.random.default_rng(1)
    sel = rng.choice(len(P), 200000, replace=False)
    gaps = []
    for k in range(len(names)):
        a = sel[W[sel] == k]
        b = np.flatnonzero(W != k)
        if a.size:
            dist, idx = cKDTree(P[b]).query(P[a], k=1, workers=2)
            gaps.append(dist)
    gaps = np.concatenate(gaps)
    report['nearest_other_wrap_sv'] = {'p10': float(np.percentile(gaps, 10)), 'median': float(np.median(gaps)),
                                       'p90': float(np.percentile(gaps, 90))}
    out = ROOT / 'score/kt1_controls.json'
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
