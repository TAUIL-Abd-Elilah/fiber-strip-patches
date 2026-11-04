"""band_dataset.py: assemble a villa ``fit_spiral --dataset`` root for the PHerc0139 band of NOVEMBER_TARGET_v2
(volume 20260102150214, fit frame = L2 = 9.596 um voxels, z-ROI L2 [3200, 4200), inputs clipped to [3000, 4400)).

Subcommands (all CPU, <= 2 threads, no GPU):
  build     umbilicus.json (L2 control points clipped to the margin band), fibers/ (the 620 human VC3D fiber JSONs
            clipped to the margin band, branches remapped), spiral-scroll.json (catalog flags, voxel size, L2 base
            shape, lasagna group/scale read from the store's own .zattrs), configs/*.json (arm A, arm B, seeds 1 and 2)
  lasagna   mirror the z rows of the open-data Lasagna L2 store (group "4": 16x of L0 = 4x of L2) that cover the
            margin band into lasagna_inputs/las_008_{nx,ny,grad_mag}.ome.zarr (resumable; stops if C: < 25 GB free
            or the download exceeds --max-gb); then writes lasagna.done
  pack      build villa's resident-pool sidecars (pack_resident_pools.py) for the mirrored stores
  validate  run villa main's fit_session.validate_session_request on every config and write validate.json

Credits: the dataset layout and spiral-scroll.json contract are villa's (ScrollPrize/villa spiral-fitting, MIT;
pinned main baf5e605 at C:/VesuviusTemp/nov_snap/villa_main). The chunk-row mirror is adapted from the October
harness tools/mirror_zarr_fast.py of TAUIL-Abd-Elilah/spiral-patches-ab (MIT). The fiber JSON clipper follows the
field rules of villa's vc3d_fiber_format parser and spiral_helpers.load_fiber_point_collection.

Python: C:/Users/PC/miniconda3/envs/vesuvius/python.exe . Set PYTHONPATH to include villa_extra/ (the baf5e605
vc3d_fiber_format package, which the sparse villa_main checkout lacks).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path('C:/VesuviusTemp/nov_strips')
DATASET = ROOT / 'dataset'
VILLA_SF = Path('C:/VesuviusTemp/nov_snap/villa_main/spiral-fitting')
VILLA_EXTRA = ROOT / 'villa_extra'
PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'

SCROLL = 'PHerc0139'
VOLUME = '20260102150214'
L0_UM = 2.399
FIT_LEVEL = 2                      # the fit frame is L2 of the 2.399 um scan
L0_PER_SV = 2 ** FIT_LEVEL         # 4 base voxels per fit voxel
VOXEL_UM = L0_UM * L0_PER_SV       # 9.596
BASE_SHAPE_L2 = [19239, 6628, 6628]   # ceil([76953, 26511, 26511] / 4): the CT zarr level-2 shape (PREREG v3.2 sec 3)
Z_ROI = (3200, 4200)               # fit z-ROI, L2
Z_CLIP = (3000, 4400)              # inputs clipped to this (200-slice margin each side), L2

UMBILICUS_L2_SRC = Path('C:/VesuviusTemp/strips/data/umbilicus/PHerc0139_20260102150214_umbilicus_L2.json')
FIBERS_SRC = Path('C:/VesuviusTemp/strips/data/human/0139')
CATALOG = ROOT / 'dl' / 'metadata_decoded.json'

BUCKET = 'https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com'
LASAGNA_PREFIX = (f'{SCROLL}/representations/predictions/lasagna/'
                  f'{VOLUME}-lasagna-20260419180421-L2')
LASAGNA_STORES = {   # dataset name -> S3 store name
    'las_008_nx.ome.zarr': f'{SCROLL}-{VOLUME}-lasagna-20260724_nx.ome.zarr',
    'las_008_ny.ome.zarr': f'{SCROLL}-{VOLUME}-lasagna-20260724_ny.ome.zarr',
    'las_008_grad_mag.ome.zarr': f'{SCROLL}-{VOLUME}-lasagna-20260724_grad_mag.ome.zarr',
}
LASAGNA_GROUP = '4'      # the store's coarsest-but-one level: 16x of L0 = 4x of the L2 fit frame (its .zattrs)
LASAGNA_SCALE = 4        # relative to the fit frame

MIN_FREE_GB = 25.0


def free_gb(path='C:/'):
    return shutil.disk_usage(path).free / 1e9


def jdump(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)


# --------------------------------------------------------------------------------------------------------------
# build: umbilicus, fibers, spiral-scroll.json, configs
# --------------------------------------------------------------------------------------------------------------

def clip_umbilicus(src, dst, z_clip):
    """Copy the L2 umbilicus JSON keeping the control points with z in the clip band plus one point beyond each
    side (so interp1d covers the band without extrapolating)."""
    data = json.loads(Path(src).read_text(encoding='utf-8'))
    pts = sorted(data['control_points'], key=lambda p: p['z'])
    zs = np.asarray([p['z'] for p in pts], dtype=np.float64)
    inside = np.flatnonzero((zs >= z_clip[0]) & (zs < z_clip[1]))
    lo = max(0, int(inside.min()) - 1) if inside.size else 0
    hi = min(len(pts) - 1, int(inside.max()) + 1) if inside.size else len(pts) - 1
    kept = pts[lo:hi + 1]
    out = {k: v for k, v in data.items() if k != 'control_points'}
    out['control_points'] = kept
    out['_clip'] = {'source': str(src), 'units': 'L2 voxels (9.596 um)', 'z_clip': list(z_clip),
                    'kept_control_points': len(kept), 'source_control_points': len(pts)}
    jdump(out, dst)
    return {'kept': len(kept), 'source': len(pts), 'z_first': kept[0]['z'], 'z_last': kept[-1]['z']}


def _control_line_indices(line_xyz, control_xyz):
    """Each control point's nearest line point (the rule of spiral_helpers.load_fiber_point_collection)."""
    idx = np.empty(len(control_xyz), dtype=np.int64)
    for k, c in enumerate(control_xyz):
        idx[k] = int(np.argmin(((line_xyz - c) ** 2).sum(axis=1)))
    return idx


def plan_fiber_clip(data, z_clip_l0):
    """Decide the clip of one fiber JSON so villa's loader fits exactly what it would fit on the full fiber inside the
    band. villa keeps only the line points between a fiber's first and last control point
    (spiral_helpers.load_fiber_point_collection), so: take the first and last line point of that controlled span with
    z in [z_clip_l0[0], z_clip_l0[1]) (L0 voxels), keep the control points inside them plus the nearest control point
    on each side, and cut the line at the outermost kept control points. Returns None when the controlled span never
    enters the band or fewer than 2 control points exist.

    Changed 4 Nov 2026 after KT1_CHECK P1: requiring >= 2 control points inside the band dropped 6 V fibers (about
    6,000 sv in band) that villa would fit and the strip plan runs, and cut the in-band stretch outside the outermost
    in-band control point of every other fiber, so arm B would have seen geometry arm A did not."""
    line = np.asarray(data['line_points'], dtype=np.float64).reshape(-1, 3)
    controls = data['control_points']
    if len(line) == 0 or len(controls) < 2:
        return None
    control_xyz = np.asarray([c['position'] if isinstance(c, dict) else c for c in controls], dtype=np.float64)
    cli = _control_line_indices(line, control_xyz)
    span = np.arange(int(cli.min()), int(cli.max()) + 1)
    inside = span[(line[span, 2] >= z_clip_l0[0]) & (line[span, 2] < z_clip_l0[1])]
    if inside.size == 0:
        return None
    i0, i1 = int(inside.min()), int(inside.max())
    keep = {k for k in range(len(controls)) if i0 <= cli[k] <= i1}
    before = [k for k in range(len(controls)) if cli[k] < i0]
    after = [k for k in range(len(controls)) if cli[k] > i1]
    if before:
        keep.add(max(before, key=lambda k: cli[k]))
    if after:
        keep.add(min(after, key=lambda k: cli[k]))
    keep_controls = sorted(keep)
    if len(keep_controls) < 2:
        return None
    return {'line_span': (int(cli[keep_controls].min()), int(cli[keep_controls].max())),
            'keep_controls': keep_controls, 'control_line_indices': cli.tolist()}


def apply_fiber_clip(data, plan, kept_control_maps):
    """Write the clipped fiber: line_points[i0:i1+1]; the kept control points (the last one loses segment_to_next, as
    the format requires of a final control point); branches whose own endpoint survives and whose partner fiber is
    in the band set, with both control_point_index fields remapped through ``kept_control_maps``
    ({basename: {old index: new index}}); adjacent_branches likewise."""
    i0, i1 = plan['line_span']
    keep = plan['keep_controls']
    remap = {old: new for new, old in enumerate(keep)}
    out = dict(data)
    out['line_points'] = data['line_points'][i0:i1 + 1]
    controls = []
    for new, old in enumerate(keep):
        c = data['control_points'][old]
        if isinstance(c, dict):
            c = dict(c)
            if new == len(keep) - 1:
                c.pop('segment_to_next', None)
        controls.append(c)
    out['control_points'] = controls
    dropped = {'branches': 0, 'adjacent_branches': 0}
    for key in ('branches', 'adjacent_branches'):
        kept_list = []
        for br in data.get(key) or []:
            own = br.get('control_point_index')
            partner_file = os.path.basename(br.get('branch_file') or '')
            partner_idx = br.get('branch_control_point_index')
            partner_map = kept_control_maps.get(partner_file)
            if (own in remap and partner_map is not None and partner_idx in partner_map):
                nb = dict(br)
                nb['control_point_index'] = remap[own]
                nb['branch_control_point_index'] = partner_map[partner_idx]
                kept_list.append(nb)
            else:
                dropped[key] += 1
        if key in data:
            out[key] = kept_list
    out['band_clip'] = {'z_clip_l2': list(Z_CLIP), 'z_clip_l0': [Z_CLIP[0] * L0_PER_SV, Z_CLIP[1] * L0_PER_SV],
                        'line_point_span': [i0, i1], 'source_line_points': len(data['line_points']),
                        'source_control_points': len(data['control_points']),
                        'kept_control_point_indices': keep, 'dropped': dropped,
                        'source': 'dl.ash2txt.org/other/annotators/0139_fibers (local copy of 28 Oct 2026)'}
    return out, dropped


def clip_fibers(src_dir, dst_dir, z_clip):
    z_l0 = (z_clip[0] * L0_PER_SV, z_clip[1] * L0_PER_SV)
    files = sorted(Path(src_dir).glob('*.json'))
    datas, plans = {}, {}
    for f in files:
        d = json.loads(f.read_text(encoding='utf-8'))
        p = plan_fiber_clip(d, z_l0)
        if p is not None:
            datas[f.name] = d
            plans[f.name] = p
    maps = {name: {old: new for new, old in enumerate(p['keep_controls'])} for name, p in plans.items()}
    dst = Path(dst_dir)
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    stats = {'source_files': len(files), 'kept_files': 0, 'dropped_branches': 0, 'dropped_adjacent': 0,
             'families': {}, 'line_points': 0, 'control_points': 0, 'versions': {}}
    for name, d in datas.items():
        out, dropped = apply_fiber_clip(d, plans[name], maps)
        with open(dst / name, 'w', encoding='utf-8') as fh:
            json.dump(out, fh)
        stats['kept_files'] += 1
        stats['dropped_branches'] += dropped['branches']
        stats['dropped_adjacent'] += dropped['adjacent_branches']
        stats['line_points'] += len(out['line_points'])
        stats['control_points'] += len(out['control_points'])
        hv = (d.get('hv_classification') or {})
        fam = hv.get('manual_tag') or hv.get('automatic_tag') or '?'
        stats['families'][fam] = stats['families'].get(fam, 0) + 1
        stats['versions'][str(d.get('version'))] = stats['versions'].get(str(d.get('version')), 0) + 1
    return stats


def verify_fibers_with_villa(fibers_dir):
    """Parse every clipped fiber with villa main's own loader (CPU) and return counts."""
    sys.path.insert(0, str(VILLA_SF))
    sys.path.insert(0, str(VILLA_EXTRA))
    from spiral_helpers import load_fiber_point_collections, resolve_fiber_links
    pcls, _ = load_fiber_point_collections(str(fibers_dir), 0, min_point_spacing=40.0,
                                           base_shape_zyx=tuple(BASE_SHAPE_L2))
    zs = np.concatenate([np.asarray([pt['zyx'][0] if 'zyx' in pt else pt['p'][2]
                                     for pt in pcl['points'].values()], dtype=np.float64)
                         for pcl in pcls.values()]) if pcls else np.zeros(0)
    scales = sorted({pcl['metadata']['input_coordinate_scale'] for pcl in pcls.values()})
    links = resolve_fiber_links(pcls)
    return {'loaded': len(pcls), 'points': int(sum(len(p['points']) for p in pcls.values())),
            'z_min_l2': float(zs.min()) if zs.size else None, 'z_max_l2': float(zs.max()) if zs.size else None,
            'coordinate_scales': scales, 'resolved_links': len(links),
            'pending_links': int(sum(1 for l in links if l.get('pending')))}


def catalog_flags():
    m = json.loads(CATALOG.read_text(encoding='utf-8'))
    p = m['samples'][SCROLL]['volumes'][VOLUME]['properties']
    return {'z_direction_is_top_to_bottom': p['z_direction_is_top_to_bottom'],
            'left_handed_coordinates': p['left_handed_coordinates'],
            'shape_l0': p['shape'], 'pixel_size_um': p['pixel_size_um'],
            'superseded_by': p.get('superseded_by'), 'license': p.get('license', {}).get('name')}


def write_scroll_spec(dst):
    sys.path.insert(0, str(VILLA_SF))
    from surface_orientation import spiral_outward_sense_for
    flags = catalog_flags()
    sense = spiral_outward_sense_for(flags['z_direction_is_top_to_bottom'], flags['left_handed_coordinates'])
    spec = {
        'schema_version': 1,
        'name': SCROLL,
        'voxel_size_um': VOXEL_UM,
        'z_direction_is_top_to_bottom': flags['z_direction_is_top_to_bottom'],
        'left_handed_coordinates': flags['left_handed_coordinates'],
        'spiral_outward_sense': sense,
        'base_shape_zyx': BASE_SHAPE_L2,
        'normal_zarr_group': LASAGNA_GROUP,
        'lasagna_scale': LASAGNA_SCALE,
        'umbilicus': {'coordinate_scale': 1.0},
    }
    jdump(spec, dst)
    jdump({'volume': f'{VOLUME}-{L0_UM}um-0.2m-78keV-masked.zarr', 'sample_id': SCROLL,
           'source': f'{BUCKET}/metadata.json (gzip; Last-Modified Mon, 02 Nov 2026 11:32:29 GMT), '
                     f'samples.{SCROLL}.volumes.{VOLUME}.properties',
           **flags, 'spiral_outward_sense': sense,
           'rule': "villa main surface_orientation.spiral_outward_sense_for: 'ACW' if z_direction_is_top_to_bottom "
                   "!= left_handed_coordinates else 'CW'",
           'fit_frame': f'L{FIT_LEVEL} = {VOXEL_UM} um; base_shape_zyx = ceil(shape_l0 / {L0_PER_SV})',
           'lasagna': {'store': LASAGNA_PREFIX, 'group': LASAGNA_GROUP,
                       'zattrs_scale_vs_L0': 16.0, 'lasagna_scale_vs_fit_frame': LASAGNA_SCALE},
           'z_roi_l2': list(Z_ROI), 'z_clip_l2': list(Z_CLIP)},
          Path(dst).parent / 'catalog_orientation.json')
    return spec, flags


COMMON = {
    # the band
    'z_begin': Z_ROI[0], 'z_end': Z_ROI[1],
    'optimizer_num_training_steps': 20000,
    'optimizer_random_seed': 1,
    # NOVEMBER_TARGET_v2 sec 2.3 item 1
    'dense_spacing_mode': 'grad_mag',
    'input_use_winding_inference': False,
    'input_use_tracks': False,
    # the 0813 harness (C:/VesuviusTemp/band0813/configs/common.json) keys that still exist in baf5e605
    'loss_weight_shell_outer': 0,
    'loss_start_track_dt': 10000,
    'loss_start_patch_dt': 10000,
    'sample_count_tracks_per_step': 24000,
    'sample_count_track_points_per_step': 64,
    'sample_count_dense_normal_points': 30000,
    # no outer shell on 0139 (shell weight 0): keep the optional input out of validation
    'input_use_outer_shell': False,
    # 0813 set loss_weight_dense_spacing 0 because PHerc0813 has no grad_mag store; 0139 L2 ships one, so the
    # grad_mag spacing term keeps villa's default weight (12.0). Recorded as a deviation in configs/NOTES.json.
    'loss_weight_dense_spacing': 12.0,
}
ARM_A = {'input_disable_patches': True}
ARM_B = {'input_disable_patches': False, 'patch_uuid_filter_regex': None}
DROPPED_0813_KEYS = ['loss_weight_shell_patch_radius', 'loss_start_unverified_patch_dt',
                     'sample_count_dense_spacing_pairs', 'sample_count_dense_spacing_density_extra_pairs',
                     'sample_count_dense_spacing_density_chunk_pairs', 'sample_count_dense_attachment_points']


def write_configs(cfg_dir):
    sys.path.insert(0, str(VILLA_SF))
    from config import Config
    cfg_dir = Path(cfg_dir)
    written = {}
    for arm, extra in (('A', ARM_A), ('B', ARM_B)):
        for seed in (1, 2):
            cfg = {**COMMON, **extra, 'optimizer_random_seed': seed}
            Config(cfg)   # raises on unknown keys, wrong types or out-of-range values
            name = f'config_{arm}.json' if seed == 1 else f'config_{arm}_seed{seed}.json'
            jdump(cfg, cfg_dir / name)
            written[name] = cfg
    jdump({'common': COMMON, 'arm_A': ARM_A, 'arm_B': ARM_B,
           'dropped_0813_keys_missing_in_baf5e605': DROPPED_0813_KEYS,
           'deviations_from_0813': {
               'loss_weight_dense_spacing': '0813: 0 (no grad_mag store); here villa default 12.0 (0139 L2 has grad_mag)',
               'input_use_outer_shell': 'false here (0813 relied on a local shell-optional patch)',
               'unverified patches': 'villa main has no unverified-patch input; arm B uses verified_patches'},
           'villa': 'C:/VesuviusTemp/nov_snap/villa_main baf5e605bb42a3d55a62b7c5c728e0908137225c',
           'num_windings': 'not set (UNKNOWN for PHerc0139): villa defaults shell_outer_winding_idx=130, '
                           'model_gap_expander_num_windings=130, capacity 144'},
          cfg_dir / 'NOTES.json')
    return written


def cmd_build(args):
    DATASET.mkdir(parents=True, exist_ok=True)
    (DATASET / 'verified_patches').mkdir(exist_ok=True)
    report = {'dataset': str(DATASET), 'z_roi_l2': list(Z_ROI), 'z_clip_l2': list(Z_CLIP)}
    report['umbilicus'] = clip_umbilicus(UMBILICUS_L2_SRC, DATASET / 'umbilicus.json', Z_CLIP)
    print('umbilicus', report['umbilicus'], flush=True)
    report['fibers'] = clip_fibers(FIBERS_SRC, DATASET / 'fibers', Z_CLIP)
    print('fibers', report['fibers'], flush=True)
    spec, flags = write_scroll_spec(DATASET / 'spiral-scroll.json')
    report['spiral_scroll'] = spec
    report['catalog'] = flags
    print('spiral-scroll.json', spec, flush=True)
    report['configs'] = sorted(write_configs(ROOT / 'configs'))
    report['fibers_villa_loader'] = verify_fibers_with_villa(DATASET / 'fibers')
    print('villa loader on clipped fibers', report['fibers_villa_loader'], flush=True)
    jdump(report, ROOT / 'logs' / 'build.json')
    print('BUILD_OK', flush=True)


# --------------------------------------------------------------------------------------------------------------
# lasagna: mirror chunk rows of the open-data store (adapted from spiral-patches-ab tools/mirror_zarr_fast.py)
# --------------------------------------------------------------------------------------------------------------

_local = threading.local()


def _session():
    import requests
    if not hasattr(_local, 's'):
        _local.s = requests.Session()
    return _local.s


def _get(url, tries=6):
    import requests
    for t in range(tries):
        try:
            r = _session().get(url, timeout=120)
            if r.status_code in (403, 404):
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if t == tries - 1:
                raise
            time.sleep(2 * (t + 1))


def _list_keys(prefix):
    keys, token = [], None
    ns = '{http://s3.amazonaws.com/doc/2006-03-01/}'
    while True:
        params = {'list-type': '2', 'prefix': prefix, 'max-keys': '1000'}
        if token:
            params['continuation-token'] = token
        r = _session().get(BUCKET + '/', params=params, timeout=120)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        keys += [(c.find(ns + 'Key').text, int(c.find(ns + 'Size').text)) for c in root.iter(ns + 'Contents')]
        if root.find(ns + 'IsTruncated').text != 'true':
            return keys
        token = root.find(ns + 'NextContinuationToken').text


def mirror_rows(remote_root, group, local_root, z0, z1, workers, max_bytes, budget):
    """Mirror the chunk rows of ``remote_root/group`` covering lasagna z [z0, z1) into ``local_root``.
    ``budget`` is a dict shared across stores: {'bytes': downloaded so far, 'stop': reason or None}."""
    t0 = time.time()
    local_root = Path(local_root)
    (local_root / group).mkdir(parents=True, exist_ok=True)
    for rel in ('.zgroup', '.zattrs', f'{group}/.zarray', f'{group}/.zattrs'):
        b = _get(f'{BUCKET}/{remote_root}/{rel}')
        if b is not None:
            (local_root / rel).write_bytes(b)
    meta = json.loads((local_root / group / '.zarray').read_text())
    assert meta.get('dimension_separator', '.') == '/', 'row listing assumes "/"-separated chunk keys'
    Z, cz = meta['shape'][0], meta['chunks'][0]
    rows = range(z0 // cz, (min(z1, Z) - 1) // cz + 1)
    with ThreadPoolExecutor(workers) as pool:
        listed = list(pool.map(lambda k: _list_keys(f'{remote_root}/{group}/{k}/'), rows))
    pat = re.compile(r'/(\d+)/(\d+)/(\d+)$')
    todo, n_listed, listed_bytes = [], 0, 0
    for keys in listed:
        for key, size in keys:
            if not pat.search(key):
                continue
            n_listed += 1
            listed_bytes += size
            rel = key[len(remote_root) + 1:]
            p = local_root.joinpath(*rel.split('/'))
            if not (p.exists() and p.stat().st_size == size):
                todo.append((key, p, size))
    print(f'{remote_root}/{group}: rows {rows.start}..{rows.stop - 1}, {n_listed} chunks listed '
          f'({listed_bytes / 1e9:.3f} GB), {len(todo)} to fetch', flush=True)
    if listed_bytes + budget['bytes'] > max_bytes:
        budget['stop'] = f'listed size {listed_bytes / 1e9:.2f} GB + so far {budget["bytes"] / 1e9:.2f} GB exceeds cap'
        return {'listed': n_listed, 'listed_bytes': listed_bytes, 'fetched': 0, 'fetched_bytes': 0}
    done = [0, 0]
    lock = threading.Lock()

    def one(item):
        if budget['stop']:
            return
        key, p, size = item
        b = _get(f'{BUCKET}/{key}')
        if b is None or len(b) != size:
            raise IOError(f'{key}: got {None if b is None else len(b)} bytes, listed {size}')
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + '.part')
        tmp.write_bytes(b)
        os.replace(tmp, p)
        with lock:
            done[0] += 1
            done[1] += len(b)
            budget['bytes'] += len(b)
            if done[0] % 500 == 0:
                print(f'  {done[0]}/{len(todo)} chunks, {done[1] / 1e9:.3f} GB ({time.time() - t0:.0f}s), '
                      f'C: free {free_gb():.1f} GB', flush=True)
                if free_gb() < MIN_FREE_GB:
                    budget['stop'] = f'C: free {free_gb():.1f} GB < {MIN_FREE_GB}'
                if budget['bytes'] > max_bytes:
                    budget['stop'] = f'downloaded {budget["bytes"] / 1e9:.2f} GB > cap'

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, todo))
    print(f'done {remote_root}/{group} z[{z0},{z1}) {n_listed} chunks present, {done[1] / 1e9:.3f} GB new '
          f'({time.time() - t0:.0f}s)' + (f' STOPPED: {budget["stop"]}' if budget['stop'] else ''), flush=True)
    return {'listed': n_listed, 'listed_bytes': listed_bytes, 'fetched': done[0], 'fetched_bytes': done[1],
            'rows': [rows.start, rows.stop - 1]}


def cmd_lasagna(args):
    out_dir = DATASET / 'lasagna_inputs'
    out_dir.mkdir(parents=True, exist_ok=True)
    z0 = int(np.floor(Z_CLIP[0] / LASAGNA_SCALE))
    z1 = int(np.ceil(Z_CLIP[1] / LASAGNA_SCALE))
    budget = {'bytes': 0, 'stop': None}
    report = {'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'lasagna_z': [z0, z1], 'group': LASAGNA_GROUP,
              'c_free_gb_before': free_gb(), 'stores': {}, 'max_gb': args.max_gb, 'workers': args.workers}
    if free_gb() < MIN_FREE_GB:
        report['stop'] = f'C: free {free_gb():.1f} GB < {MIN_FREE_GB} before start'
    else:
        for local_name, remote_name in LASAGNA_STORES.items():
            if budget['stop']:
                break
            report['stores'][local_name] = mirror_rows(
                f'{LASAGNA_PREFIX}/{remote_name}', LASAGNA_GROUP, out_dir / local_name, z0, z1,
                args.workers, args.max_gb * 1e9, budget)
        report['stop'] = budget['stop']
    report['downloaded_gb'] = budget['bytes'] / 1e9
    report['c_free_gb_after'] = free_gb()
    report['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    report['ok'] = report.get('stop') is None
    jdump(report, ROOT / 'logs' / 'lasagna.json')
    (ROOT / 'logs' / 'lasagna.done').write_text('OK' if report['ok'] else f'STOPPED {report["stop"]}')
    print('LASAGNA_OK' if report['ok'] else f'LASAGNA_STOPPED {report["stop"]}', flush=True)


def cmd_pack(args):
    import subprocess
    cmd = [PY, '-u', str(VILLA_SF / 'pack_resident_pools.py'), str(DATASET / 'lasagna_inputs'),
           '--what', 'normals,grad_mag', '--normal-group', LASAGNA_GROUP, '--io-threads', '2']
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '-1', 'FIT_SPIRAL_DEVICE': 'cpu', 'PYTHONIOENCODING': 'utf-8',
           'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2'}
    print(' '.join(cmd), flush=True)
    rc = subprocess.call(cmd, env=env, cwd=str(VILLA_SF))
    sidecars = sorted(p.name for p in (DATASET / 'lasagna_inputs').glob('*.respool_*'))
    metas = {}
    for s in sidecars:
        mp = DATASET / 'lasagna_inputs' / s / 'meta.json'
        if mp.exists():
            m = json.loads(mp.read_text())
            metas[s] = {k: m.get(k) for k in ('array_shape', 'rows', 'brick_shape', 'channel_names')}
    jdump({'rc': rc, 'sidecars': metas}, ROOT / 'logs' / 'pack.json')
    print('PACK_OK' if rc == 0 else f'PACK_FAILED rc={rc}', flush=True)
    (ROOT / 'logs' / 'pack.done').write_text('OK' if rc == 0 else f'FAILED {rc}')


# --------------------------------------------------------------------------------------------------------------
# validate: villa main's cheap pre-GPU validation of every config
# --------------------------------------------------------------------------------------------------------------

def cmd_validate(args):
    os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')
    sys.path.insert(0, str(VILLA_SF))
    sys.path.insert(0, str(VILLA_EXTRA))
    from fit_session import (SpiralRunConfig, conventional_input_paths, load_scroll_spec, resolve_dataset_root,
                             validate_session_request)
    from config import Config
    res = resolve_dataset_root(str(DATASET))
    spec = load_scroll_spec(str(DATASET))
    paths = conventional_input_paths(str(DATASET), spec, output_directory=str(ROOT / 'out'),
                                     cache_directory=str(ROOT / 'cache' / 'spiral'))
    report = {'villa': str(VILLA_SF), 'dataset': str(DATASET),
              'resolution': {'resolved': res.resolved, 'missing_required': res.missing_required,
                             'missing_optional': res.missing_optional, 'warnings': res.warnings,
                             'ambiguities': res.ambiguities},
              'scroll_spec': spec.manifest(), 'paths': {k: v for k, v in paths.__dict__.items() if k != 'pcls'},
              'validate_session_request': {}}
    ok = not res.missing_required and not res.ambiguities

    def cli_tolerated(error):
        # validate_session_request is the service's check: it lists the conventional point-collection files
        # (abs_winding.json, relative_windings.json, same_windings.json, drawn_control_points.json) that
        # conventional_input_paths always names; the headless CLI skips an absent one with a warning
        # (fit_session.PCL_ROLE_CONVENTIONS comment; load_point_collection). Anything else blocks the fit.
        return error['field'].startswith('pcls[') and error['message'].startswith('PCL file does not exist')

    report['validate_session_request_blocking'] = {}
    for cfg_path in sorted((ROOT / 'configs').glob('config_*.json')):
        cfg = json.loads(cfg_path.read_text())
        full = Config(cfg).as_dict()
        run = SpiralRunConfig(z_begin=full['z_begin'], z_end=full['z_end'], config=full)
        errors = validate_session_request(paths, run)
        blocking = [e for e in errors if not cli_tolerated(e)]
        report['validate_session_request'][cfg_path.name] = errors
        report['validate_session_request_blocking'][cfg_path.name] = blocking
        print(cfg_path.name, 'errors:', len(errors), 'blocking:', blocking, flush=True)
        ok = ok and not blocking
    report['VALIDATE_OK'] = bool(ok)
    jdump(report, ROOT / 'logs' / 'validate.json')
    print('VALIDATE_OK' if ok else 'VALIDATE_FAILED', flush=True)
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('build').set_defaults(fn=cmd_build)
    p = sub.add_parser('lasagna')
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--max-gb', type=float, default=6.0)
    p.set_defaults(fn=cmd_lasagna)
    sub.add_parser('pack').set_defaults(fn=cmd_pack)
    sub.add_parser('validate').set_defaults(fn=cmd_validate)
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == '__main__':
    sys.exit(main())
