"""Unit checks of what the stage 2 copies add: the disk guard, the CT free, the resume-aware prefetch, the stall watchdog.
Runs in a temporary folder with a faked disk and a faked S3; deletes nothing of the real cache.

    python -I -B test_stage2_tools.py [--with-stall]     (the stall check takes about 3 minutes)
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import types

TOOLS = Path(__file__).resolve().parent
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS/f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rb = load('run_band')
ch = load('chain')
GIB = 2**30


class FakeDisk:
    """free = base + one GiB per file deleted from ``root`` since construction."""

    def __init__(self, root, base):
        self.root, self.base = Path(root), base
        self.n0 = sum(1 for _ in self.root.rglob('*') if _.is_file())

    def __call__(self, _):
        n = sum(1 for _ in self.root.rglob('*') if _.is_file())
        return types.SimpleNamespace(free=int((self.base+self.n0-n)*GIB), total=0, used=0)


def args(tmp, **kw):
    d = dict(plan='p', runplan='r', afv='a', root=str(tmp), done_name='INFER_DONE', min_free_gib=36., hard_floor_gib=34.5,
             guard_wait_min=0., stall_min=.5, affinity=0, workers=2, batch=16, threads=8, only_pieces=None)
    d.update(kw)
    return argparse.Namespace(**d)


def touch_chunks(root, keys):
    for k in keys:
        f = Path(root)/'/'.join(map(str, k))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b'x')


def test_guard(tmp):
    root = Path(tmp)/'ct'
    keys = {'A': [(0, 0, 0), (0, 0, 1)], 'B': [(0, 0, 1), (0, 0, 2)], 'C': [(0, 0, 3)], 'D': [(0, 0, 4)]}
    orig = shutil.disk_usage
    try:
        # above the guard: nothing happens
        touch_chunks(root, {k for v in keys.values() for k in v})
        r = rb.Runner(args(Path(tmp)/'r1'))
        r.pending = ['B', 'C', 'D']
        rb.shutil.disk_usage = FakeDisk(root, 40.)
        r.guard_tick(keys, root, '/')
        assert all((root/'0/0'/str(i)).exists() for i in range(5))
        # under the guard, above the hard floor: only A's own chunk goes, not the one B shares
        rb.shutil.disk_usage = FakeDisk(root, 35.)
        r.guard_tick(keys, root, '/')
        assert not (root/'0/0/0').exists() and (root/'0/0/1').exists() and (root/'0/0/2').exists()
        assert (root/'0/0/3').exists() and (root/'0/0/4').exists()
        # under the hard floor with no finished chunk left: the LAST pending piece goes, the current one never
        r = rb.Runner(args(Path(tmp)/'r2'))
        r.pending = ['B', 'C', 'D']
        keys2 = {k: v for k, v in keys.items() if k != 'A'}
        r.cached_pieces = {'D', 'C'}
        rb.shutil.disk_usage = FakeDisk(root, 34.)   # one more GiB per delete; the guard needs 36: D then C go
        r.guard_tick(keys2, root, '/')
        assert (root/'0/0/1').exists() and (root/'0/0/2').exists(), 'the current piece lost a chunk'
        assert not (root/'0/0/4').exists()
        assert 'D' not in r.cached_pieces
    finally:
        rb.shutil.disk_usage = orig
    print('guard ok')


def test_free(tmp):
    root = Path(tmp)/'x/PHerc0139/volumes/v.zarr/2'
    touch_chunks(root, [(1, 2, 3), (1, 2, 4), (7, 8, 9)])
    (root/'.locks').mkdir()
    (root/'.locks/1.2.3').write_text('l')
    (root/'.zarray').write_text('{}')
    (root/'.zattrs').write_text('{}')
    (root/'1/2/3.tmp99').write_text('t')
    (root/'1/2/odd').write_text('o')
    n, size, kept = ch.free_ct({(1, 2, 4)}, root)
    assert (n, kept) == (3, 1), (n, kept)
    assert (root/'1/2/4').exists() and (root/'.zarray').exists() and (root/'.zattrs').exists()
    assert (root/'.locks/1.2.3').exists() and (root/'1/2/odd').exists()
    assert not (root/'1/2/3').exists() and not (root/'7/8/9').exists() and not (root/'1/2/3.tmp99').exists()
    for bad in (Path(tmp)/'x/PHerc0332/2', Path(tmp)/'x/PHerc0139/3'):
        try:
            ch.free_ct(set(), bad)
        except RuntimeError:
            continue
        raise AssertionError(f'free_ct accepted {bad}')
    print('free_ct ok')


def test_done_rc(tmp):
    f = Path(tmp)/'DONE'
    assert ch.done_rc(f) is None
    f.write_text('rc=3 infer_rc=3 x=1\n')
    assert ch.done_rc(f) == 3
    f.write_text('garbage')
    assert ch.done_rc(f) is None
    print('done_rc ok')


def test_prefetch(tmp):
    cache = Path(tmp)/'cache'
    root = cache/'s3'/rb.BUCKET/rb.VOL/str(rb.LEVEL)
    root.mkdir(parents=True)
    (root/'.zarray').write_text('{}')
    meta = dict(chunks=[2, 2, 2], shape=[64, 64, 64], dimension_separator='/', fill_value=0)
    keys = {'A': [(0, 0, 0)], 'B': [(0, 0, 1), (0, 0, 2)]}
    rows = [dict(piece='A'), dict(piece='B')]
    got = []

    class Sess:
        def mount(self, *a):
            pass

        def get(self, url, timeout=None):
            got.append(url.rsplit('/', 3)[-3:])
            return types.SimpleNamespace(status_code=200, content=b'\0'*8)
    orig_cache, orig_sess, orig_disk = rb.CACHE, rb.requests.Session, shutil.disk_usage
    try:
        rb.CACHE = cache
        rb.requests.Session = Sess
        r = rb.Runner(args(Path(tmp)/'p1'))
        # A is finished: its chunk must not be fetched on a resume
        (r.root/'records').mkdir()
        (r.root/'strips/A/strip').mkdir(parents=True)
        (r.root/'records/A.json').write_text(json.dumps(dict(status='ok')))
        (r.root/'strips/A/strip.npz').write_text('x')
        (r.root/'strips/A/strip/meta.json').write_text('{}')
        rb.shutil.disk_usage = lambda _: types.SimpleNamespace(free=100*GIB)
        r.prefetch(rows, keys, meta)
        assert sorted(tuple(map(int, g)) for g in got) == [(0, 0, 1), (0, 0, 2)], got
        assert 'B' in r.cached_pieces and r.prefetch_done.is_set() and not r.prefetch_stopped
        # disk low and no room coming: the prefetch stops after the wait, nothing fetched
        got.clear()
        shutil.rmtree(root/'0')
        r = rb.Runner(args(Path(tmp)/'p2', guard_wait_min=0.))
        rb.shutil.disk_usage = lambda _: types.SimpleNamespace(free=35*GIB)
        r.prefetch(rows, keys, meta)
        assert not got and r.prefetch_stopped and r.prefetch_done.is_set()
    finally:
        rb.CACHE, rb.requests.Session = orig_cache, orig_sess
        rb.shutil.disk_usage = orig_disk
    print('prefetch ok')


def test_stall(tmp):
    r = rb.Runner(args(Path(tmp)/'s1', stall_min=.5))
    out, err = r.root/'o.out', r.root/'e.err'
    script = Path(tmp)/'sleeper.py'
    script.write_text('import time\ntime.sleep(900)\n')
    rc = r.run_py([str(script)], out, err, str(tmp))
    assert rc != 0
    assert 'STALL' in (r.root/'run.log').read_text()
    print('stall watchdog ok, rc', rc)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--with-stall', action='store_true')
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(dir=TOOLS.parent) as d:
        test_guard(d)
        test_free(d)
        test_done_rc(d)
        test_prefetch(d)
        if a.with_stall:
            test_stall(d)
    print('all ok')
