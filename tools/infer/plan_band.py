"""Plan the November band pieces: every human PHerc0139 fiber's part inside L2 z [Z0, Z1], as October pieces.

    python -I -B plan_band.py --out PLAN.json [--z0 3000 --z1 4400] [--min-window-sv 16]

Reuses the frozen October planner unchanged (C:/VesuviusTemp/strips/score/score_strips.py: load_fibers,
load_full_run_maps, plan_pieces, number_pieces, piece_ct, budget) with band windows in place of matched stretches:
a window is a maximal run of a fiber's 1-sv samples (controlled span) whose z lies in [Z0, Z1] (sv = level-2 voxel).
Each window gets the decision heads of a full infer_all run within HEAD_MARGIN_SV (40) of it, and each piece keeps
PIECE_BEFORE_SV (300) before its first head and PIECE_AFTER_SV (160) after its last head, cut at line points and
merged when overlapping, exactly as the October plans. The plan JSON has the matched_stretches.json layout, so
score/tools/make_piece_afv.py (frozen) writes the piece AFV and the exact --arc run plan from it.
Only fibers with an H/V tag are planned (make_piece_afv.py refuses untagged ones, as in October); untagged fibers
touching the band are listed. CT: r = CT_RADIUS (170) level-2 voxels around each piece's head path, against the
October cache. Nothing is written outside --out. Run order: pieces whose chunks are all cached first, then by the
number of chunks to fetch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

SCORE = Path('C:/VesuviusTemp/strips/score')
sys.path.insert(0, str(SCORE))
import score_strips as S  # noqa: E402

VOL = 'PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr'
ZARRAY = f'https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/{VOL}/2'
SPACE = 'PHerc0139/20260102150214@L0'
CACHE = 'C:/VesuviusTemp/strips/ct_cache'


def band_windows(fiber, z0, z1, min_len):
    """Maximal runs of the fiber's samples with z in [z0, z1] (sv), at least ``min_len`` sv long."""
    inside = (fiber.points[:, 2] >= z0) & (fiber.points[:, 2] <= z1)
    out = []
    for i0, i1 in S.consecutive_runs(np.flatnonzero(inside)):
        s0, s1 = float(fiber.s[i0]), float(fiber.s[i1])
        if s1-s0 < min_len:
            continue
        pts = fiber.points[i0:i1+1]
        out.append(dict(fiber=fiber.name, file=fiber.file, uuid=fiber.uuid, family=fiber.family,
                        family_source=fiber.family_source, annotator=fiber.annotator, segment='band',
                        i0=int(i0), i1=int(i1), s0=s0, s1=s1, length_sv=s1-s0, length_mm=(s1-s0)*S.SV_UM*1e-3,
                        samples=int(i1-i0+1), z_sv=[float(pts[:, 2].min()), float(pts[:, 2].max())],
                        centre_l0=(pts.mean(0)*S.SCORE_UNIT_BASE).tolist(),
                        foldbacks=int(sum(s0 <= x <= s1 for x in fiber.flags.get('foldback_s', []))),
                        jumps=int(sum(s0 <= x <= s1 for x in fiber.flags.get('jump_s', [])))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--z0', type=float, default=3000.)
    ap.add_argument('--z1', type=float, default=4400.)
    ap.add_argument('--band', type=float, nargs=2, default=(3200., 4200.), help='the fit band (information)')
    ap.add_argument('--min-window-sv', type=float, default=16.)
    ap.add_argument('--fibers', default=str(SCORE/'data'/'fibers0139'))
    ap.add_argument('--full-run-map', default=str(SCORE/'data'/'full_run_map_0139.npz'))
    a = ap.parse_args()
    t0 = time.time()
    fibers, skipped = S.load_fibers(a.fibers, space=SPACE)
    tagged = [f for f in fibers if f.family_source != 'geometry']
    untagged = [f for f in fibers if f.family_source == 'geometry']
    print(f'{len(fibers)} fibers ({len(skipped)} skipped, {len(untagged)} untagged)', flush=True)
    fmaps = S.load_full_run_maps(a.full_run_map, tagged)
    windows, pieces, touching, untagged_touching = [], [], [], []
    for f in tagged:
        ws = band_windows(f, a.z0, a.z1, a.min_window_sv)
        if not ws:
            continue
        touching.append(f.name)
        windows += ws
    for f in untagged:
        if band_windows(f, a.z0, a.z1, a.min_window_sv):
            untagged_touching.append(f.name)
    windows.sort(key=lambda w: (w['fiber'], w['s0']))
    for n, w in enumerate(windows):
        w['id'] = f'B{n:04d}'
    by_name = {f.name: f for f in tagged}
    for fname in sorted({w['fiber'] for w in windows}):
        pieces += S.plan_pieces(by_name[fname], [w for w in windows if w['fiber'] == fname], fmaps[fname])
    S.number_pieces(pieces, 'N', windows)
    zarray = S.fetch_zarray(ZARRAY)
    cached = S.piece_ct(by_name, pieces, zarray, CACHE, VOL)
    full = S.budget(pieces, zarray, cached)
    for p in pieces:
        p['ct_chunks_cached'] = len(p['_ct'] & cached)
        p['ct_chunks_to_fetch'] = len(p['_ct']-cached)
    order = sorted(pieces, key=lambda p: (p['ct_chunks_to_fetch'] > 0, p['ct_chunks_to_fetch'], p['id']))
    for n, p in enumerate(order):
        p['run'] = True
        p['run_order'] = n
    for w in windows:
        w['run'] = True
    # fiber-level band facts
    in_fit_band = sum(1 for f in tagged+untagged if ((f.points[:, 2] >= a.band[0]) & (f.points[:, 2] <= a.band[1])).any())
    sha = hashlib.sha256(SCORE.joinpath('score_strips.py').read_bytes()).hexdigest()
    plan = dict(pieces=len(pieces), volume_zarray=ZARRAY,
                zarray=dict(shape=zarray['shape'], chunks=zarray['chunks'], dtype=zarray.get('dtype')),
                all_matched=full, run=full, subsampled=False, caps=None, full_run_map=a.full_run_map,
                run_stretches=dict(stretches=len(windows), fibers=len(touching),
                                   length_mm=float(sum(w['length_mm'] for w in windows)),
                                   by_family={fam: dict(stretches=sum(w['family'] == fam for w in windows),
                                                        fibers=len({w['fiber'] for w in windows if w['family'] == fam}))
                                              for fam in ('H', 'V')}),
                ct_chunks_union=len(set().union(*[p['_ct'] for p in pieces])),
                ct_chunks_cached_union=len(set().union(*[p['_ct'] for p in pieces]) & cached))
    out = dict(provenance=dict(planner=str(Path(__file__).resolve()), scorer=str(SCORE/'score_strips.py'),
                               scorer_sha256=sha, scorer_version=S.SCORER_VERSION, argv=sys.argv[1:],
                               constants=S.CONSTANTS, written=time.strftime('%Y-%m-%d %H:%M:%S')),
               analysis='band', band=dict(window_z_sv=[a.z0, a.z1], fit_band_z_sv=list(a.band),
                                          min_window_sv=a.min_window_sv, coordinate_space=SPACE,
                                          rule='windows: maximal runs of 1-sv fiber samples (controlled span) with '
                                               'z in [z0, z1]; pieces: score_strips.plan_pieces as in October'),
               min_stretch_mm=a.min_window_sv*S.SV_UM*1e-3, min_stretch_sv=a.min_window_sv, segments=[],
               segment_log=None, fibers_skipped=skipped, fibers_untagged=[f.name for f in untagged],
               fibers_untagged_touching_band=untagged_touching, fibers_touching_fit_band_any_tag=in_fit_band,
               G1=None, plan=plan, stretches=[S._public(w) for w in windows], pieces=[S._public(pc) for pc in pieces],
               dropped_overlaps=[],
               fibers=[dict(fiber=f.name, file=f.file, uuid=f.uuid, uuid_source=f.uuid_source, afv_id=f.afv_id,
                            family=f.family, family_source=f.family_source, length_sv=f.length,
                            length_mm=f.length*S.SV_UM*1e-3, line_offset=f.line_offset,
                            stretches=sum(w['fiber'] == f.name for w in windows),
                            foldbacks=f.flags.get('foldbacks'), jumps=f.flags.get('jumps'))
                       for f in tagged if f.name in set(touching)])
    Path(a.out).write_text(json.dumps(S.jsonable(out), indent=1))
    print(json.dumps(S.jsonable(dict(fibers_touching=len(touching), untagged_touching=len(untagged_touching),
                                     windows=len(windows), plan=plan, seconds=round(time.time()-t0, 1))), indent=1))


if __name__ == '__main__':
    main()
