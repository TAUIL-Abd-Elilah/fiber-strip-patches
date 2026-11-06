"""Write FREEZE_B2.txt (PREREG amendment 2): sha256 of the band-2 configs, jobs and tools, and tree hashes of the local inputs."""
import glob
import hashlib
import json
import os

N = 'C:/VesuviusTemp/nov_strips'


def h(p):
    s = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            s.update(b)
    return s.hexdigest()


def tree(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root).replace(os.sep, '/')] = h(p)
    return hashlib.sha256(json.dumps(sorted(out.items())).encode()).hexdigest(), len(out)


lines = ['# Frozen inputs of PREREG.md amendment 2 (band 2, L2 z 4400-5400). sha256; tree hashes are over sorted (path, sha256) pairs.', '']
rels = (['PREREG.md'] + sorted(glob.glob('configs/band2/*')) + ['jobs/job_b2_A1.sh', 'jobs/job_b2_B1.sh']
        + sorted(glob.glob('tools/band2/*.py')) + ['tools/score_purity.py', 'tools/score_band.py'])
for rel in rels:
    lines.append(f'{h(rel)}  {rel.replace(os.sep, "/")}')
for name, root in [('patches/0139_z4400-5400', 'patches/0139_z4400-5400'),
                   ('local dataset_b2/verified_patches (the same 107 pieces without manifest.json)', N + '/dataset_b2/verified_patches'),
                   ('local dataset_b2/fibers (131 clipped human fibers, not redistributed)', N + '/dataset_b2/fibers'),
                   ('local stage2/0139/score/band01/segments_masked (36 wraps, not redistributed)',
                    N + '/stage2/0139/score/band01/segments_masked')]:
    t, n = tree(root)
    lines.append(f'{t}  TREE {name} ({n} files)')
for rel in ['dataset_b2/umbilicus.json', 'dataset_b2/spiral-scroll.json', 'score/covered_masks_b2.npz']:
    lines.append(f'{h(N + "/" + rel)}  local {rel}')
lines += ['', 'Fitter: villa baf5e605bb42a3d55a62b7c5c728e0908137225c, spiral-fitting/fit_spiral.py unchanged.']
with open('FREEZE_B2.txt', 'w', newline='\n') as f:
    f.write('\n'.join(lines) + '\n')
print('\n'.join(lines))
