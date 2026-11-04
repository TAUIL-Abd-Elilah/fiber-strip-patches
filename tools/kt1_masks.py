"""Masked, band-clipped copies of the PHerc 0139 wrap segments for KT1 (rules: KT1_SCORING_RULES.md).

Reads the October segment copies, writes tifxyz copies under score/segments_masked with -1 on masked or out-of-band
nodes, cropped to their valid rows/columns, and records per-wrap counts and the #2167 sector in kt1_masks.json.
The source files are only read. CPU, numpy + tifffile.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np
import tifffile

SRC = Path('C:/VesuviusTemp/strips/score/data/segments')
ROOT = Path('C:/VesuviusTemp/nov_strips')
DST = ROOT / 'score' / 'segments_masked'
UMB = ROOT / 'dataset' / 'umbilicus.json'
L0_PER_SV = 4
Z0, Z1 = 3200 * L0_PER_SV, 4200 * L0_PER_SV     # L0 band
W042 = (15616, 17152)                           # villa #1547, inclusive L0 z
SECTOR_WRAPS = ('w034', 'w035', 'w036', 'w037')
Z_BIN = 100 * L0_PER_SV
WIDEN_DEG = 5


def wrap_id(name):
    m = re.search(r'-(w\d{3})_', name)
    return m.group(1) if m else None


def load(d):
    grid = np.stack([tifffile.imread(d / f'{c}.tif').astype(np.float64) for c in 'xyz'], -1)
    valid = np.isfinite(grid).all(-1) & ~(grid == -1).any(-1)
    return grid, valid


def umbilicus_xy(z_l0):
    pts = sorted(json.loads(UMB.read_text())['control_points'], key=lambda p: p['z'])
    z = np.array([p['z'] for p in pts]) * L0_PER_SV
    return (np.interp(z_l0, z, [p['x'] * L0_PER_SV for p in pts]),
            np.interp(z_l0, z, [p['y'] * L0_PER_SV for p in pts]))


def angles(grid):
    ux, uy = umbilicus_xy(grid[..., 2])
    return np.degrees(np.arctan2(grid[..., 1] - uy, grid[..., 0] - ux)) % 360.0


def largest_gap(deg):
    """Largest circular run of empty 1-degree bins: (start bin, width)."""
    occ = np.zeros(360, bool)
    occ[np.floor(deg).astype(int) % 360] = True
    if occ.all() or not occ.any():
        return None
    best, start = (0, 0), None
    doubled = np.r_[occ, occ]
    for i, o in enumerate(doubled):
        if not o and start is None:
            start = i
        if o and start is not None:
            if i - start > best[0]:
                best = (i - start, start % 360)
            start = None
    return best[1], min(best[0], 360)


def sector_table(grid, valid):
    z = grid[..., 2]
    table = {}
    for b0 in range(Z0, Z1, Z_BIN):
        sel = valid & (z >= b0) & (z < b0 + Z_BIN)
        table[b0] = largest_gap(angles(grid)[sel]) if sel.any() else None
    return table


def in_sector(grid, table):
    z = grid[..., 2]
    ang = angles(grid)
    out = np.zeros(z.shape, bool)
    for b0, gap in table.items():
        if gap is None:
            continue
        start, width = gap
        rel = (ang - (start - WIDEN_DEG)) % 360.0
        out |= (z >= b0) & (z < b0 + Z_BIN) & (rel <= width + 2 * WIDEN_DEG)
    return out


def main():
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)
    dirs = sorted(d for d in SRC.iterdir() if (d / 'x.tif').exists())
    w035 = next(d for d in dirs if wrap_id(d.name) == 'w035')
    grid35, valid35 = load(w035)
    table = sector_table(grid35, valid35)
    known = [g for g in table.values() if g]
    report = {'band_l0': [Z0, Z1], 'source': str(SRC), 'wraps': {}, 'excluded': [],
              'sector': {'rule': 'largest empty arc of w035 per 100-slice L2 z bin, widened 5 degrees each side',
                         'per_bin_start_width_deg': {str(k): v for k, v in table.items()},
                         'start_deg_p10_p90': [float(x) for x in np.percentile([g[0] for g in known], [10, 90])],
                         'end_deg_p10_p90': [float(x) for x in np.percentile([(g[0] + g[1]) % 360 for g in known],
                                                                             [10, 90])],
                         'width_deg_median': float(np.median([g[1] for g in known])),
                         'chase_2167_published': {'start_deg': [327, 5], 'end_deg': [71, 85], 'width_median_deg': 98}}}
    for d in dirs:
        wid = wrap_id(d.name)
        if wid is None:
            report['excluded'].append({'name': d.name, 'why': 'not a wrap (title)'})
            continue
        if wid == 'w046':
            report['excluded'].append({'name': d.name, 'why': 'villa #1547: duplicate of w045'})
            continue
        grid, valid = load(d)
        z = grid[..., 2]
        band = valid & (z >= Z0) & (z < Z1)
        keep = band.copy()
        masked_w042 = masked_sector = 0
        if wid == 'w042':
            m = keep & (z >= W042[0]) & (z <= W042[1])
            masked_w042 = int(m.sum())
            keep &= ~m
        if wid in SECTOR_WRAPS:
            m = keep & in_sector(grid, table)
            masked_sector = int(m.sum())
            keep &= ~m
        if not keep.any():
            report['excluded'].append({'name': d.name, 'why': 'no node left in the band'})
            continue
        rows = np.flatnonzero(keep.any(1))
        cols = np.flatnonzero(keep.any(0))
        r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
        out = DST / d.name
        out.mkdir()
        for k, c in enumerate('xyz'):
            a = grid[..., k].copy()
            a[~keep] = -1
            tifffile.imwrite(out / f'{c}.tif', a[r0:r1, c0:c1].astype(np.float32))
        shutil.copy(d / 'meta.json', out / 'meta.json')
        report['wraps'][wid] = {'name': d.name, 'nodes_in_band': int(band.sum()), 'nodes_kept': int(keep.sum()),
                                'masked_w042': masked_w042, 'masked_sector': masked_sector}
        print(wid, report['wraps'][wid], flush=True)
    report['usable_wraps'] = len(report['wraps'])
    (ROOT / 'score' / 'kt1_masks.json').write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report['sector'][k] for k in report['sector'] if k != 'per_bin_start_width_deg'}, indent=1))
    print('usable wraps', report['usable_wraps'], 'excluded', report['excluded'])


if __name__ == '__main__':
    main()
