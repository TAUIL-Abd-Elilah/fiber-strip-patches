"""Write FREEZE.txt in the release repo: sha256 of PREREG, configs, jobs, tools, and tree hashes of the local inputs."""
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


lines = ['# Frozen inputs of PREREG.md, 4 Nov 2026. sha256; tree hashes are over sorted (path, sha256) pairs.', '']
rels = (['PREREG.md'] + sorted(glob.glob('configs/*')) + sorted(glob.glob('jobs/*')) + sorted(glob.glob('tools/*.py'))
        + sorted(glob.glob('tools/*/*.py')) + ['results/KT1_SCORING_RULES.md', 'results/KT1_RESULT.md',
                                               'results/kt1_masks.json', 'results/expected_error_cap.json'])
for rel in rels:
    lines.append(f'{h(rel)}  {rel.replace(os.sep, "/")}')
for name, root in [('patches/0139_band', 'patches/0139_band'),
                   ('local dataset/verified_patches', N + '/dataset/verified_patches'),
                   ('local dataset/fibers (144 clipped human fibers, not redistributed)', N + '/dataset/fibers'),
                   ('local score/segments_masked (36 wraps, not redistributed)', N + '/score/segments_masked')]:
    t, n = tree(root)
    lines.append(f'{t}  TREE {name} ({n} files)')
for rel in ['dataset/umbilicus.json', 'dataset/spiral-scroll.json']:
    lines.append(f'{h(N + "/" + rel)}  local {rel}')
lines += ['', 'Fitter: villa baf5e605bb42a3d55a62b7c5c728e0908137225c, spiral-fitting/fit_spiral.py unchanged.',
          'Strips: villa 6f2024569 + #2163, scrollprize/fiber_strip_small_v1@7bd163a22c839ff312879ae1916195d0c9729c0e.']
with open('FREEZE.txt', 'w', newline='\n') as f:
    f.write('\n'.join(lines) + '\n')
print(lines[2])
print('\n'.join(x for x in lines if 'TREE' in x))
