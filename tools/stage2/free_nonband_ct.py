"""One-off before the launch: delete the cached PHerc0139 L2 chunks no stage 2 band needs (they re-download), after checking
that FREEZE.txt pins no cache file and that no process holds the cache open. Writes ct_cleanup_prelaunch.json.

    python -I -B free_nonband_ct.py [--dry]
"""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

import psutil

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('chain', TOOLS/'chain.py')
ch = importlib.util.module_from_spec(spec)
sys.modules['chain'] = ch
spec.loader.exec_module(ch)
ROOT = TOOLS.parent
CACHE_PARENT = ch.STRIPS/'ct_cache'/'s3'/'vesuvius-challenge-open-data'


def count_files(p):
    return sum(1 for f in Path(p).rglob('*') if f.is_file())


freeze = (ch.SCORE/'FREEZE.txt').read_text(encoding='utf-8', errors='replace')
pinned = [ln for ln in freeze.splitlines() if 'ct_cache' in ln or '/volumes/' in ln]
if pinned:
    raise SystemExit(f'FREEZE.txt mentions the cache: {pinned[:3]}')
holders = []
for p in psutil.process_iter(['pid', 'name']):
    try:
        if (p.info['name'] or '').lower() == 'python.exe':
            holders += [(p.info['pid'], f.path) for f in p.open_files() if 'ct_cache' in f.path]
    except psutil.Error:
        pass
if holders:
    raise SystemExit(f'open under ct_cache: {holders[:5]}')
keep = set()
for b in json.loads((ROOT/'bands.json').read_text())['bands']:
    d = json.loads((ROOT/b['name']/'plan'/'ct_union.json').read_text())
    keep |= {tuple(k) for k in d['chunks']}
files = list(ch.chunk_files())
extra = [f for f in files if f[0] not in keep]
rep = dict(when=time.strftime('%Y-%m-%d %H:%M:%S'), freeze_lines_mentioning_cache=len(pinned), open_handles=len(holders),
           chunks_before=len(files), bands_union=len(keep), to_delete=len(extra), to_delete_gib=round(sum(f[2] for f in extra)/2**30, 3),
           c_free_before_gib=round(shutil.disk_usage('C:/').free/2**30, 2),
           others_before={n: count_files(CACHE_PARENT/n) for n in ('PHerc0332', 'PHercParis4')})
if '--dry' not in sys.argv:
    n, size, kept = ch.free_ct(keep)
    rep.update(deleted=n, deleted_gib=round(size/2**30, 3), kept=kept, c_free_after_gib=round(shutil.disk_usage('C:/').free/2**30, 2),
               others_after={n2: count_files(CACHE_PARENT/n2) for n2 in ('PHerc0332', 'PHercParis4')},
               metadata_kept=[str(p.name) for p in (ch.CT_ROOT/'.zarray', ch.CT_ROOT/'.zattrs') if p.exists()])
    (ROOT/'ct_cleanup_prelaunch.json').write_text(json.dumps(rep, indent=1))
print(json.dumps(rep, indent=1))
