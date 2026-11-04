"""pytest for strips2patches.py: one real October piece (primary P0000, inside the band) plus synthetic strips.
Run: C:/Users/PC/miniconda3/envs/vesuvius/python.exe -m pytest -q C:/VesuviusTemp/nov_strips/test_strips2patches.py
The real-piece tests skip when the October workspace or villa main is absent."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import strips2patches as s2p  # noqa: E402

REAL_PIECE = Path('C:/VesuviusTemp/strips/score/runs/v3/strips/primary/P0000')
PLAN = Path('C:/VesuviusTemp/strips/score/results/matched_stretches.json')
VILLA_SF = Path('C:/VesuviusTemp/nov_snap/villa_main/spiral-fitting')
VILLA_EXTRA = HERE / 'villa_extra'
sys.path.insert(0, str(VILLA_EXTRA))  # villa's fiber loader imports vc3d_fiber_format (absent from the sparse snapshot)


def make_strip(tmp_path, rows=40, cols=25, z0=3400.0, name='P9999', expected=None, mask_holes=()):
    """A synthetic villa-layout strip: a flat sheet, rows along z, 4 x 5 sv grid, x/y/z in sv."""
    d = tmp_path / name / 'strip'
    d.mkdir(parents=True)
    r, c = np.meshgrid(np.arange(rows), np.arange(cols), indexing='ij')
    x = 1000.0 + 5.0 * c
    y = np.full_like(x, 2000.0)
    z = z0 + 4.0 * r
    valid = np.ones((rows, cols), bool)
    for (i, j) in mask_holes:
        valid[i, j] = False
    grid = np.stack([x, y, z], -1).astype(np.float32)
    grid[~valid] = -1
    for k, n in enumerate('xyz'):
        tifffile.imwrite(d / f'{n}.tif', grid[..., k])
    tifffile.imwrite(d / 'mask.tif', (valid * 255).astype(np.uint8))
    (d / 'meta.json').write_text(json.dumps({'uuid': 'synthetic', 'scale': [0.2, 0.25], 'type': 'seg',
                                             'format': 'tifxyz', 'voxel_size_um': 9.6}))
    (d / 'trace.json').write_text(json.dumps({'trim_patch_voxels': 75.0, 'blend': 16.0,
                                              'first_row_arc_patch_voxels': 100.0, 'row_step_voxels': 4.0}))
    if expected is not None:
        tifffile.imwrite(d / 'expected_error.tif', expected.astype(np.float32))
    return d


def test_column_cap_drops_only_bad_columns(tmp_path):
    expected = np.full((40, 25), 0.8)
    expected[:, 3] = 2.5          # one column over the cap
    expected[:15, 7] = 5.0        # a column whose median stays under the cap (25 of its 40 rows are 0.8)
    d = make_strip(tmp_path, expected=expected)
    strip = s2p.Strip(d)
    valid, rec = s2p.convert_strip(strip, cap=2.0, min_area_cm2=0.0, trim=75.0, z_clip=None, voxel_um=9.596)
    assert rec['columns']['dropped'] == [3]
    assert not valid[:, 3].any() and valid[:, 7].all()
    assert rec['trim']['applied_by'].startswith('villa infer.py --trim 75')
    assert 'dropped' not in rec


def test_z_clip_and_min_area(tmp_path):
    d = make_strip(tmp_path, rows=40, z0=4300.0, expected=np.full((40, 25), 0.5))   # z 4300..4456
    strip = s2p.Strip(d)
    valid, rec = s2p.convert_strip(strip, cap=2.0, min_area_cm2=0.0, trim=75.0, z_clip=(3000.0, 4400.0),
                                   voxel_um=9.596)
    assert valid.sum() == 25 * 25           # rows with z < 4400: r = 0..24
    assert rec['z_clip']['nodes_removed'] == 15 * 25
    # area: 24 x 24 quads of 20 vx2 at 9.596 um
    assert rec['valid_quads'] == 24 * 24
    assert abs(rec['area_cm2'] - 24 * 24 * 20 * 9.596 ** 2 / 1e8) < 1e-9
    _, rec2 = s2p.convert_strip(strip, cap=2.0, min_area_cm2=0.5, trim=75.0, z_clip=(3000.0, 4400.0), voxel_um=9.596)
    assert rec2['dropped'].startswith('area')
    _, rec3 = s2p.convert_strip(strip, cap=2.0, min_area_cm2=0.0, trim=75.0, z_clip=(5000.0, 6000.0), voxel_um=9.596)
    assert rec3['dropped'] == 'no valid quad left'


def test_trim_ends_matches_villa_rule():
    keep = np.ones((10, 3), bool)
    out = s2p.trim_ends(keep, 60.0, 4.0, 160.0, 75.0)   # rows at arc 60..96: kept where 75 <= arc <= 85
    arcs = 60.0 + 4.0 * np.arange(10)
    assert (out.all(axis=1) == ((arcs >= 75.0) & (arcs <= 85.0))).all()


def test_convert_writes_villa_loadable_patch(tmp_path):
    d = make_strip(tmp_path, expected=np.full((40, 25), 0.5))
    out = tmp_path / 'vp'
    s2p.main(['convert', '--strips', str(tmp_path), '--out', str(out), '--cap', '2.0', '--min-area-cm2', '0.0',
              '--z-clip', '3000', '4400'])
    man = json.loads((out / 'manifest.json').read_text())
    assert man['patches_written'] == 1 and man['pieces_dropped'] == 0
    name = next(iter(man['patches']))
    assert name.endswith('__0')
    meta = json.loads((out / name / 'meta.json').read_text())
    assert meta['format'] == 'tifxyz' and meta['scale'] == [0.2, 0.25]
    assert meta['provenance']['strip_model'].startswith('scrollprize/fiber_strip_small_v1')
    if not VILLA_SF.exists():
        pytest.skip('villa main not present')
    os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')
    sys.path.insert(0, str(VILLA_SF))
    from tifxyz import load_tifxyz
    patch = load_tifxyz(str(out / name))
    assert int(patch.valid_vertex_mask.sum()) == 40 * 25
    assert abs(float(patch.area) - 39 * 24 * 20) < 1e-3


@pytest.mark.skipif(not REAL_PIECE.exists() or not PLAN.exists(), reason='October workspace absent')
def test_real_piece_P0000_stitch_and_identity():
    strip = s2p.Strip(REAL_PIECE / 'strip')
    assert strip.expected is not None, strip.notes
    assert strip.expected_source.startswith('stitched from strip.npz')
    assert any(n.startswith('stitch check: 100.0%') for n in strip.notes), strip.notes
    e = strip.expected[strip.valid]
    assert np.isfinite(e).all() and 0.0 < np.median(e) < 3.0
    fiber, prov = s2p.fiber_identity(strip, s2p.load_plans([PLAN]))
    assert fiber == 'kb_20260904T021448778_000085' and prov['family'] == 'H'
    valid, rec = s2p.convert_strip(strip, cap=2.0, min_area_cm2=0.05, trim=75.0, z_clip=(3000.0, 4400.0),
                                   voxel_um=9.596)
    assert 'dropped' not in rec and rec['z_clip']['nodes_removed'] == 0   # P0000 lies at L2 z 3433..3572
    assert rec['area_cm2'] > 0.05


@pytest.mark.skipif(not REAL_PIECE.exists() or not VILLA_SF.exists(), reason='October workspace or villa absent')
def test_real_piece_round_trip_through_villa_loader(tmp_path):
    os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')
    out = tmp_path / 'vp'
    s2p.main(['convert', '--strips', str(REAL_PIECE), '--out', str(out), '--plan', str(PLAN)])
    man = json.loads((out / 'manifest.json').read_text())
    assert man['patches_written'] == 1
    name = next(iter(man['patches']))
    sys.path.insert(0, str(VILLA_SF))
    from spiral_helpers import load_patches
    patches = load_patches(str(out))
    assert list(patches) == [name]
    p = patches[name]
    assert int(p.valid_vertex_mask.sum()) == man['patches'][name]['valid_nodes']
    assert abs(float(p.area) - man['patches'][name]['area_vx2']) < 1e-2
