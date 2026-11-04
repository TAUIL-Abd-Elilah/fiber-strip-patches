"""strips2patches.py: turn sheet-strip model output into villa ``verified_patches`` (tifxyz) for ``fit_spiral``.

NOVEMBER_TARGET_v2 section 2.3 item 2. For every strip folder the pinned runner wrote (villa's tifxyz: x/y/z.tif,
meta.json, optional mask.tif, trace.json; per-decision ``expected_error_vox`` in strip.npz, or a stitched
expected_error.tif):
  1. trim 75 sv at true fiber ends (the October rule; villa's infer.py --trim already applies it at the ends of what
     it ran, so a strip whose trace.json records trim_patch_voxels >= --trim is left as is and the fact recorded);
  2. drop columns (across-fiber positions) whose median expected_error over the strip's valid rows exceeds a cap
     that is pre-registered from the October runs (``cap-stats``; default 2.0 sv);
  3. mask nodes outside the band's z clip (L2 [3000, 4400) by default);
  4. drop pieces under a minimum area (default 0.05 cm2);
  5. write ``verified_patches/<fiber>__<k>/`` with x/y/z.tif (-1 = invalid), mask.tif, expected_error.tif (NaN =
     invalid; ignored by villa's loader), villa's meta.json kept with its bbox/area refreshed and a ``provenance``
     block (model, villa commit, fiber, parameters), plus ``manifest.json`` (patch -> fiber, area, expected_error).
No filtering against the wrap segments, ever: they are the held-out truth.

Credits: the strip model, its inference tool and the stitching functions below are sean's (bruniss, villa #2110,
``vesuvius/neural_tracing/tracers/fibers/sheet_strip/infer.py`` at 6f2024569, MIT); ``orient_decisions``,
``stitch``, ``stitch_values`` and ``trim_ends`` are copied from it unchanged. The per-node expected_error stitch and
the row-alignment check follow ``frames_from_decisions`` of the October scorer (TAUIL-Abd-Elilah/
fiber-strips-beyond-paris4 ``score/score_strips.py``, MIT). The target format is villa's ``tifxyz.py``
(``load_tifxyz`` / ``save_tifxyz`` at baf5e605). The team's ``anchored_strip_merge`` prototype (Paris 4
verified_patches, Aug 2026) is the prior art for strips as patch input.

usage:
  strips2patches.py cap-stats --strips ROOT [ROOT ...] --out expected_error_cap.json [--cap 2.0]
  strips2patches.py convert --strips ROOT [ROOT ...] --out verified_patches_dir [--plan PLAN.json ...]
      [--cap-file expected_error_cap.json | --cap 2.0] [--min-area-cm2 0.05] [--trim 75] [--z-clip 3000 4400]
      [--only PIECE ...] [--voxel-um 9.596]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import tifffile

VERSION = '0.1'
STRIP_MODEL = 'scrollprize/fiber_strip_small_v1@7bd163a22c839ff312879ae1916195d0c9729c0e'
STRIP_VILLA = 'ScrollPrize/villa 6f2024569 + #2163 (C:/VesuviusTemp/strips/villa_6f2)'
DEFAULT_CAP_SV = 2.0
DEFAULT_MIN_AREA_CM2 = 0.05
DEFAULT_TRIM_SV = 75.0
DEFAULT_Z_CLIP = (3000.0, 4400.0)
DEFAULT_VOXEL_UM = 9.596     # L2 of the 2.399 um PHerc0139 scan; villa's strip writer labels it 9.6
STITCH_TOLERANCE_SV = 0.05   # float32 tifxyz rounding is ~1e-3 at these coordinates (October scorer)


# ---- copied from villa sheet_strip/infer.py (6f2024569), MIT --------------------------------------------------

def trim_ends(keep, first_arc, row_step, length, margin):
    """``keep`` (R, C; rows along the fiber, row r at arclength ``first_arc + r*row_step``) without the rows beyond
    ``margin`` inside either end of a fiber of ``length`` (one unit throughout)."""
    arc = first_arc + np.arange(len(keep)) * row_step
    return keep & ((arc >= margin) & (arc <= length - margin))[:, None]


def orient_decisions(heights, frames):
    """Keep one side of the fiber in every column: each decision's v axis turned to agree with the previous one's.
    Returns the oriented heights, frames and which decisions flipped (K,)."""
    flipped = np.zeros(len(frames), bool)
    for k in range(1, len(frames)):
        flipped[k] = flipped[k - 1] ^ (float(frames[k, :, 1] @ frames[k - 1, :, 1]) < 0)
    oriented = np.where(flipped[:, None, None], heights[:, :, ::-1], heights)
    oriented_frames = frames.copy()
    oriented_frames[flipped, :, 1] *= -1  # the v column reversed is v -> -v: the same points
    oriented_frames[flipped, :, 0] *= -1  # and u -> -u keeps the frame right-handed; heights follow
    oriented[flipped] *= -1
    return oriented, oriented_frames, flipped


def stitch_values(values, arcs, f, blend, weights=None):
    """Per strip node (R, Nv): the stitch weights' average of a per-point value (K, Nf, Nv) of the decisions (as
    ``stitch``, which averages their points), NaN where no decision weighs in."""
    df = f[1] - f[0]
    rows = np.rint((arcs[:, None] - arcs[0] + f[None] - f[0]) / df).astype(np.int64)
    window = np.where(np.abs(f) < blend, np.cos(np.pi * f / (2 * blend)) ** 2, 0.)
    w = window[None, :, None] * (np.ones_like(values) if weights is None else weights)
    shape = (int(rows.max()) + 1, values.shape[2])
    total, first = np.zeros(shape), np.zeros(shape)
    flat_rows = np.broadcast_to(rows[..., None], values.shape).ravel()
    flat_cols = np.broadcast_to(np.arange(values.shape[2]), values.shape).ravel()
    np.add.at(total, (flat_rows, flat_cols), w.ravel())
    np.add.at(first, (flat_rows, flat_cols), (w * values).ravel())
    return np.where(total > 0, first / np.maximum(total, 1e-12), np.nan)


def stitch(heights, frames, positions, arcs, f, v, blend, weights=None):
    """Average every decision's strip points (world, trace voxels) into rows at arclength ``arcs[0]+f[0]+r*df``.
    ``heights`` (K, Nf, Nv) in each decision's frame; ``weights`` (K, Nf, Nv) masks points (None: all). Returns the
    rows (R, Nv, 3), the summed weight (R, Nv) and the weighted RMS distance of the decisions' points from the mean."""
    df = f[1] - f[0]
    rows = np.rint((arcs[:, None] - arcs[0] + f[None] - f[0]) / df).astype(np.int64)  # (K, Nf)
    window = np.where(np.abs(f) < blend, np.cos(np.pi * f / (2 * blend)) ** 2, 0.)
    w = window[None, :, None] * (np.ones_like(heights) if weights is None else weights)
    local = np.stack(np.broadcast_arrays(heights, v[None, None], f[None, :, None]), -1)  # (K, Nf, Nv, 3): u, v, f
    world = positions[:, None, None] + np.einsum('kfvj,kij->kfvi', local, frames)
    shape = (int(rows.max()) + 1, len(v))
    total, first, second = np.zeros(shape), np.zeros((*shape, 3)), np.zeros(shape)
    flat_rows = np.broadcast_to(rows[..., None], heights.shape).ravel()
    flat_cols = np.broadcast_to(np.arange(len(v)), heights.shape).ravel()
    np.add.at(total, (flat_rows, flat_cols), w.ravel())
    np.add.at(first, (flat_rows, flat_cols), w.reshape(-1, 1) * world.reshape(-1, 3))
    np.add.at(second, (flat_rows, flat_cols), w.ravel() * (world ** 2).sum(-1).ravel())
    mean = first / np.maximum(total, 1e-12)[..., None]
    spread = np.sqrt(np.maximum(second / np.maximum(total, 1e-12) - (mean ** 2).sum(-1), 0.))
    return mean, total, spread

# ---- end of the villa copies ---------------------------------------------------------------------------------


class Strip:
    """One strip folder: grid (R, C, 3) xyz in sv, valid (R, C), per-node expected_error (R, C) or None."""

    def __init__(self, tifxyz_dir):
        self.dir = Path(tifxyz_dir)
        self.piece_dir = self.dir.parent if self.dir.name == 'strip' else self.dir
        self.name = self.piece_dir.name
        self.meta = json.loads((self.dir / 'meta.json').read_text(encoding='utf-8'))
        x = tifffile.imread(self.dir / 'x.tif').astype(np.float64)
        y = tifffile.imread(self.dir / 'y.tif').astype(np.float64)
        z = tifffile.imread(self.dir / 'z.tif').astype(np.float64)
        self.grid = np.stack([x, y, z], -1)
        valid = ~np.all(self.grid == -1, axis=-1)
        if (self.dir / 'mask.tif').exists():
            m = tifffile.imread(self.dir / 'mask.tif')
            valid &= (m[..., 0] if m.ndim == 3 else m) != 0
        self.valid = valid
        self.trace = {}
        for cand in (self.dir / 'trace.json', self.piece_dir / 'summary.json'):
            if cand.exists():
                self.trace = {**json.loads(cand.read_text(encoding='utf-8')), **self.trace}
        self.notes = []
        self.expected = None
        self.expected_source = None
        if (self.dir / 'expected_error.tif').exists():
            e = tifffile.imread(self.dir / 'expected_error.tif').astype(np.float64)
            if e.shape == self.valid.shape:
                self.expected, self.expected_source = np.where(valid, e, np.nan), 'expected_error.tif'
            else:
                self.notes.append(f'expected_error.tif shape {e.shape} != grid {self.valid.shape}; ignored')
        if self.expected is None:
            npz = next((p for p in (self.piece_dir / 'strip.npz', self.dir / 'strip.npz') if p.exists()), None)
            if npz is None:
                self.notes.append('no expected_error.tif and no strip.npz: no expected_error')
            else:
                try:
                    self.expected = self._expected_from_decisions(npz)
                    self.expected_source = f'stitched from {npz.name} expected_error_vox'
                except Exception as error:
                    self.notes.append(f'decisions unusable ({type(error).__name__}: {error}); no expected_error')

    def _expected_from_decisions(self, npz_path):
        z = np.load(npz_path)
        if 'expected_error_vox' not in z.files:
            raise ValueError('strip.npz has no expected_error_vox')
        tpp = float(z['trace_per_patch'])
        blend = float(self.trace.get('blend', 16.))
        arcs, f, v = (z[k].astype(np.float64) for k in ('arcs', 'f', 'v'))
        heights, frames, positions = (z[k].astype(np.float64) for k in ('heights', 'frames', 'positions'))
        oriented, oframes, flipped = orient_decisions(heights, frames)
        rows, weight, _ = stitch(oriented, oframes, positions, arcs, f, v, blend)
        rows = rows / tpp
        if rows.shape[:2] != self.valid.shape:
            raise ValueError(f'stitched rows {rows.shape[:2]} != tifxyz grid {self.valid.shape}')
        both = self.valid & (weight > 0)
        if not both.any():
            raise ValueError('no node is both valid in the tifxyz and covered by the decisions')
        gap = np.linalg.norm(rows[both] - self.grid[both], axis=-1)
        share = float((gap <= STITCH_TOLERANCE_SV).mean())
        if share < 0.99:
            raise ValueError(f'decisions reproduce only {share:.1%} of the strip nodes within {STITCH_TOLERANCE_SV} sv')
        self.notes.append(f'stitch check: {share:.1%} of {int(both.sum())} nodes within {STITCH_TOLERANCE_SV} sv '
                          f'(max gap {gap.max():.4f} sv)')
        ev = z['expected_error_vox'].astype(np.float64)
        ev = np.where(flipped[:, None, None], ev[:, :, ::-1], ev)
        expected = stitch_values(ev, arcs, f, blend)
        return np.where(self.valid, expected, np.nan)


def discover_strips(roots):
    """Every folder holding x.tif + meta.json with format tifxyz (villa infer.py's ``strip/``, infer_all's
    ``strips/BUCKET/fiber_UUID/``), except patch_sheet renders."""
    found = []
    for root in roots:
        for p in sorted(Path(root).rglob('x.tif')):
            d = p.parent
            if d.name == 'patch_sheet' or not (d / 'meta.json').exists():
                continue
            try:
                if json.loads((d / 'meta.json').read_text(encoding='utf-8')).get('format') != 'tifxyz':
                    continue
            except Exception:
                continue
            found.append(d)
    return found


def load_plans(plan_paths):
    """piece AFV id (the ``fiber`` field of the runner's summary.json / trace.json) -> {fiber, parent_uuid, family,
    annotator, id} from the October plan JSONs (pieces[]). Keyed by AFV id, not by piece id: the primary and
    secondary plans both number their pieces from P0000."""
    out = {}
    for path in plan_paths or []:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
        for p in d.get('pieces', []):
            out[int(p['afv_id'])] = {'fiber': p.get('fiber'), 'parent_uuid': p.get('parent_uuid'),
                                     'family': p.get('family'), 'annotator': p.get('annotator'),
                                     'afv_id': p.get('afv_id'), 'id': p.get('id'),
                                     'parent_file': p.get('parent_file'), 'plan': str(path)}
    return out


def fiber_identity(strip, plans):
    """(fiber name used in the patch folder name, provenance dict)."""
    afv_id = strip.trace.get('fiber')
    if afv_id is not None and int(afv_id) in plans:
        p = plans[int(afv_id)]
        return p['fiber'], {'fiber_uuid': p.get('parent_uuid'), 'fiber_file': p.get('parent_file'),
                            'family': p.get('family'), 'annotator': p.get('annotator'),
                            'piece': strip.name, 'piece_plan_id': p.get('id'), 'piece_afv_id': p.get('afv_id'),
                            'plan': p.get('plan')}
    # villa infer_all layout: strips/BUCKET/fiber_UUID/
    if strip.dir.name != 'strip':
        return strip.dir.name, {'fiber_uuid': strip.dir.name, 'piece': None}
    fiber = strip.trace.get('fiber')
    return str(fiber) if fiber is not None else strip.name, {'fiber_uuid': None, 'piece': strip.name,
                                                                'piece_afv_id': fiber}


def column_medians(expected, valid):
    """Per column: the median expected_error over the valid rows (NaN when a column has no valid node)."""
    out = np.full(expected.shape[1], np.nan)
    for c in range(expected.shape[1]):
        vals = expected[:, c][valid[:, c] & np.isfinite(expected[:, c])]
        if vals.size:
            out[c] = float(np.median(vals))
    return out


def patch_area(valid, scale, voxel_um):
    quads = valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]
    area_vx2 = float(quads.sum()) * float(np.prod(1.0 / np.asarray(scale, dtype=np.float64)))
    return int(quads.sum()), area_vx2, area_vx2 * voxel_um ** 2 / 1e8


def convert_strip(strip, *, cap, min_area_cm2, trim, z_clip, voxel_um, fiber_length_sv=None):
    """Apply the rules to one strip. Returns (valid mask, record) where record['dropped'] names a reason when the
    piece is not kept."""
    valid = strip.valid.copy()
    rec = {'piece': strip.name, 'source_dir': str(strip.dir), 'rows': int(valid.shape[0]),
           'columns': int(valid.shape[1]), 'valid_nodes_source': int(strip.valid.sum()), 'notes': list(strip.notes),
           'expected_error_source': strip.expected_source}
    # 1. trim at true fiber ends
    recorded_trim = strip.trace.get('trim_patch_voxels')
    if recorded_trim is not None and float(recorded_trim) >= trim:
        rec['trim'] = {'requested_sv': trim, 'applied_by': f'villa infer.py --trim {recorded_trim} (piece ends)',
                       'rows_removed_here': 0}
    elif fiber_length_sv is not None and 'first_row_arc_patch_voxels' in strip.trace:
        row_step = float(strip.trace.get('row_step_voxels', 4.0))
        before = int(valid.sum())
        valid = trim_ends(valid, float(strip.trace['first_row_arc_patch_voxels']), row_step, fiber_length_sv, trim)
        rec['trim'] = {'requested_sv': trim, 'applied_by': 'strips2patches trim_ends',
                       'fiber_length_sv': fiber_length_sv, 'nodes_removed_here': before - int(valid.sum())}
    else:
        rec['trim'] = {'requested_sv': trim, 'applied_by': None,
                       'note': 'no fiber length known and the runner recorded no trim; not applied'}
    # 2. expected_error column cap
    if strip.expected is not None:
        med = column_medians(strip.expected, valid)
        drop = np.isfinite(med) & (med > cap)
        valid[:, drop] = False
        rec['columns'] = {'cap_sv': cap, 'medians_sv': [None if not np.isfinite(m) else round(float(m), 4) for m in med],
                          'dropped': [int(c) for c in np.flatnonzero(drop)], 'kept': int((~drop).sum())}
    else:
        rec['columns'] = {'cap_sv': cap, 'dropped': [], 'kept': int(valid.shape[1]),
                          'note': 'no expected_error available: no column dropped'}
    # 3. z clip
    if z_clip is not None:
        zs = strip.grid[..., 2]
        before = int(valid.sum())
        valid &= (zs >= z_clip[0]) & (zs < z_clip[1])
        rec['z_clip'] = {'range_sv': list(z_clip), 'nodes_removed': before - int(valid.sum())}
    # 4. area
    quads, area_vx2, area_cm2 = patch_area(valid, strip.meta['scale'], voxel_um)
    rec.update(valid_nodes=int(valid.sum()), valid_quads=quads, area_vx2=area_vx2, area_cm2=area_cm2)
    if strip.expected is not None and valid.any():
        e = strip.expected[valid]
        e = e[np.isfinite(e)]
        rec['expected_error_sv'] = ({'mean': float(e.mean()), 'median': float(np.median(e)),
                                     'p90': float(np.percentile(e, 90)), 'max': float(e.max()), 'nodes': int(e.size)}
                                    if e.size else None)
    else:
        rec['expected_error_sv'] = None
    if valid.any():
        zs = strip.grid[..., 2][valid]
        rec['z_range_sv'] = [float(zs.min()), float(zs.max())]
    if quads == 0:
        rec['dropped'] = 'no valid quad left'
    elif area_cm2 < min_area_cm2:
        rec['dropped'] = f'area {area_cm2:.4f} cm2 < {min_area_cm2}'
    return valid, rec


def write_patch(strip, valid, out_dir, fiber, prov_extra, rec, *, voxel_um, params):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = np.where(valid[..., None], strip.grid, -1.0).astype(np.float32)
    tifffile.imwrite(out_dir / 'x.tif', grid[..., 0])
    tifffile.imwrite(out_dir / 'y.tif', grid[..., 1])
    tifffile.imwrite(out_dir / 'z.tif', grid[..., 2])
    tifffile.imwrite(out_dir / 'mask.tif', (valid * 255).astype(np.uint8))
    if strip.expected is not None:
        tifffile.imwrite(out_dir / 'expected_error.tif', np.where(valid, strip.expected, np.nan).astype(np.float32))
    meta = dict(strip.meta)   # villa's meta.json kept; bbox and area refreshed for the new validity
    pts = strip.grid[valid]
    meta['bbox'] = [pts.min(axis=0).tolist(), pts.max(axis=0).tolist()]
    meta['area_vx2'] = rec['area_vx2']
    meta['area_cm2'] = rec['area_cm2']
    meta['voxel_size_um'] = voxel_um
    meta['provenance'] = {
        'tool': f'strips2patches.py v{VERSION} (TAUIL-Abd-Elilah, Nov 2026; derived from villa sheet_strip/infer.py '
                'output; prior art: the Vesuvius Challenge team anchored_strip_merge prototype, Aug 2026)',
        'strip_model': STRIP_MODEL,
        'strip_villa': STRIP_VILLA,
        'fit_villa_target': 'ScrollPrize/villa baf5e605 spiral-fitting verified_patches (load_patches / load_tifxyz)',
        'fiber': fiber,
        **prov_extra,
        'source_strip_dir': str(strip.dir),
        'source_meta': {k: strip.meta.get(k) for k in ('uuid', 'bbox', 'area_vx2', 'area_cm2', 'voxel_size_um')},
        'inference': {k: strip.trace.get(k) for k in ('checkpoint', 'step', 'decision_step', 'blend',
                                                       'trim_patch_voxels', 'arc_trace', 'decisions', 'units')},
        'parameters': params,
        'expected_error_source': strip.expected_source,
        'trim': rec['trim'], 'columns_dropped': rec['columns']['dropped'], 'z_clip': rec.get('z_clip'),
        'units': 'L2 voxels of PHerc0139/20260102150214 (9.596 um); x/y/z.tif -1 = invalid',
        'written': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    with open(out_dir / 'meta.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)
    return meta


def cmd_cap_stats(args):
    """Distribution of per-column median expected_error (and per node) over every strip under --strips, and the cap
    chosen before any band number is seen: --cap (default 2.0 sv). Written to --out."""
    strips = [Strip(d) for d in discover_strips(args.strips)]
    col_meds, nodes, per_strip = [], [], {}
    for s in strips:
        if s.expected is None:
            per_strip[s.name] = {'expected': None, 'notes': s.notes}
            continue
        med = column_medians(s.expected, s.valid)
        e = s.expected[s.valid & np.isfinite(s.expected)]
        col_meds += [m for m in med if np.isfinite(m)]
        nodes.append(e)
        per_strip[s.name] = {'column_medians_sv': [round(float(m), 4) if np.isfinite(m) else None for m in med],
                             'node_median_sv': float(np.median(e)) if e.size else None, 'nodes': int(e.size),
                             'columns_over_cap': int(np.sum(np.isfinite(med) & (med > args.cap)))}
    col = np.asarray(col_meds)
    allnodes = np.concatenate(nodes) if nodes else np.zeros(0)
    q = [50, 75, 90, 95, 99, 100]
    out = {'written': time.strftime('%Y-%m-%dT%H:%M:%S'), 'strips_roots': [str(Path(r)) for r in args.strips],
           'strips': len(strips), 'strips_with_expected_error': int(sum(1 for s in strips if s.expected is not None)),
           'cap_sv': args.cap, 'cap_rule': 'fixed before any band number: the default 2.0 sv of NOVEMBER_TARGET_v2 '
                                          'sec 2.3 item 2; the distribution below is recorded, not used to tune it',
           'column_medians': {'count': int(col.size),
                              'quantiles_sv': {str(p): float(np.percentile(col, p)) for p in q} if col.size else None,
                              'share_over_cap': float((col > args.cap).mean()) if col.size else None},
           'nodes': {'count': int(allnodes.size),
                     'quantiles_sv': {str(p): float(np.percentile(allnodes, p)) for p in q} if allnodes.size else None,
                     'share_over_cap': float((allnodes > args.cap).mean()) if allnodes.size else None},
           'per_strip': per_strip}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'per_strip'}, indent=1))


def cmd_convert(args):
    cap = args.cap
    cap_file = None
    if args.cap_file:
        cap_file = json.loads(Path(args.cap_file).read_text(encoding='utf-8'))
        cap = float(cap_file['cap_sv'])
    z_clip = tuple(args.z_clip) if args.z_clip else None
    plans = load_plans(args.plan)
    params = {'cap_sv': cap, 'cap_file': str(args.cap_file) if args.cap_file else None,
              'min_area_cm2': args.min_area_cm2, 'trim_sv': args.trim, 'z_clip_sv': list(z_clip) if z_clip else None,
              'voxel_um': args.voxel_um, 'patch_erode_patches': 'villa default (1), applied by the fit, not here'}
    out_root = Path(args.out)
    if args.clean and out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    dirs = discover_strips(args.strips)
    if args.only:
        dirs = [d for d in dirs if (d.parent.name if d.name == 'strip' else d.name) in set(args.only)]
    counts, patches, dropped = {}, {}, {}
    for d in dirs:
        strip = Strip(d)
        fiber, prov = fiber_identity(strip, plans)
        valid, rec = convert_strip(strip, cap=cap, min_area_cm2=args.min_area_cm2, trim=args.trim, z_clip=z_clip,
                                   voxel_um=args.voxel_um)
        rec['fiber'] = fiber
        rec.update({k: prov.get(k) for k in ('fiber_uuid', 'family', 'annotator')})
        if rec.get('dropped'):
            dropped[strip.name] = rec
            print(f'{strip.name}: dropped ({rec["dropped"]})', flush=True)
            continue
        k = counts.get(fiber, 0)
        counts[fiber] = k + 1
        name = f'{fiber}__{k}'
        write_patch(strip, valid, out_root / name, fiber, prov, rec, voxel_um=args.voxel_um, params=params)
        rec['patch'] = name
        patches[name] = rec
        print(f'{strip.name} -> {name}: {rec["area_cm2"]:.4f} cm2, {rec["valid_nodes"]} nodes, '
              f'columns dropped {rec["columns"]["dropped"]}', flush=True)
    manifest = {'tool': f'strips2patches.py v{VERSION}', 'written': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'strip_model': STRIP_MODEL, 'strip_villa': STRIP_VILLA, 'parameters': params,
                'strips_roots': [str(Path(r)) for r in args.strips], 'strips_found': len(dirs),
                'patches_written': len(patches), 'pieces_dropped': len(dropped),
                'total_area_cm2': float(sum(p['area_cm2'] for p in patches.values())),
                'total_valid_nodes': int(sum(p['valid_nodes'] for p in patches.values())),
                'fibers': sorted(counts), 'patches': patches, 'dropped': dropped,
                'note': 'no filtering against the wrap segments (held-out truth)'}
    (out_root / 'manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    print(f'{len(patches)} patches written ({manifest["total_area_cm2"]:.4f} cm2), {len(dropped)} pieces dropped '
          f'-> {out_root}', flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('cap-stats')
    p.add_argument('--strips', nargs='+', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--cap', type=float, default=DEFAULT_CAP_SV)
    p.set_defaults(fn=cmd_cap_stats)
    p = sub.add_parser('convert')
    p.add_argument('--strips', nargs='+', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--plan', nargs='*', default=[])
    p.add_argument('--cap', type=float, default=DEFAULT_CAP_SV)
    p.add_argument('--cap-file', default=None)
    p.add_argument('--min-area-cm2', type=float, default=DEFAULT_MIN_AREA_CM2)
    p.add_argument('--trim', type=float, default=DEFAULT_TRIM_SV)
    p.add_argument('--z-clip', type=float, nargs=2, default=list(DEFAULT_Z_CLIP))
    p.add_argument('--voxel-um', type=float, default=DEFAULT_VOXEL_UM)
    p.add_argument('--only', nargs='*', default=None)
    p.add_argument('--clean', action='store_true', help='remove --out first')
    p.set_defaults(fn=cmd_convert)
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == '__main__':
    sys.exit(main())
