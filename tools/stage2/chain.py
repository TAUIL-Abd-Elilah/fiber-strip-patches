"""Stage 2 chain, PHerc 0139: plan -> strip inference -> strips2patches for each z window of bands.json, unattended.

    python -I -B -u chain.py [--plan-only | --budget] [--retry-failed] [--root DIR] [--bands-file F] [--no-free]
                             [--run-band-extra "ARGS"]

Windows, in order, from bands.json. Per band (bandNN/): plan/ (band_plan.json, band.afv, runplan_band.tsv, ct_union.json,
PLAN_OK), run.log, status.json, runner_stdout.log, INFER_DONE (the runner's rc), strips/, records/, pieces/, patches/,
convert.log, CONVERT_DONE, DONE, CT_FREED. Chain: chain.log, chain_status.json, chain.lock.json, chain_stdout.log, pid.txt,
launch.json, CHAIN_DONE.

Band DONE: rc=N infer_rc=N convert_rc=N ... rc 0 all ok; 1 some piece failed after its one retry; 2 CUDA visible; 3 pieces
skipped by the disk guard; 5 FREEZE or pin mismatch; 10 other (runner); 20 convert failed. After DONE the chain frees the
band's CT: every PHerc0139 L2 chunk except those a later unfinished band needs (.zarray, .zattrs, .locks stay; PHerc0332 and
PHercParis4 are never touched). rc 2 and 5 stop the chain. CHAIN_DONE is written at the end, including on failure.

Resume: run the same command. Bands with DONE rc 0 or 1 are skipped (--retry-failed reruns rc 1); other bands run again and
redo only unfinished pieces, fetching only their CT. A live chain or runner of a previous launch (PID + create time in
chain.lock.json) makes it refuse to start, so one process runs at a time.

CPU only (CUDA_VISIBLE_DEVICES=-1), BelowNormal, affinity cores 0-11 set first thing, children inherit it. Children are
started with CREATE_NO_WINDOW. No file outside this folder is written except CT chunks in the villa cache.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

import psutil

PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'
TOOLS = Path(__file__).resolve().parent
STRIPS = Path('C:/VesuviusTemp/strips')
SCORE = STRIPS/'score'
NOV = Path('C:/VesuviusTemp/nov_strips')
CAP_FILE = NOV/'patches'/'expected_error_cap.json'
VOL = 'PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr'
CT_ROOT = STRIPS/'ct_cache'/'s3'/'vesuvius-challenge-open-data'/VOL/'2'
HTTPS_VOL = f'https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/{VOL}'
FIBERS = SCORE/'data'/'fibers0139'
FULL_AFV = STRIPS/'data'/'human_afv'/'PHerc0139_human_controlled.afv'
BASE_SHAPE = ['76953', '26511', '26511']
CORES = 12
THREADS = 8
MIN_FREE_GIB = 36.        # the runner's disk guard: the prefetch pauses here (hard limit 34; queued GPU fits need 33)
HARD_FLOOR_GIB = 34.5     # the runner's emergency eviction of pending pieces' chunks starts here
MIN_ARC_SV = 150.
CAP_SV = 2.0
MIN_AREA_CM2 = 0.05
PINS = {  # frozen inputs and the byte-identical copy; a difference stops the chain (rc 5)
    SCORE/'score_strips.py': 'd7d6d1946bc4decd72bc153958c4fb209f10f90fdca5f16b6616186f8e2c3577',
    SCORE/'tools'/'make_piece_afv.py': '5551149b513c49bcef0a26d1bdbd5bc55912df200f19007734f5908ae457d542',
    SCORE/'runs'/'v3'/'infer_cpu.py': '9b08d1c6f4aea74a9e4b5d407dc9af5fc53ee7dda913d6fad2f888d8c0d7e741',
    TOOLS/'strips2patches.py': '97715cea5a45e4952e20dcd4a8e14eed4cac91bbc9188dd07fa9ee964358d182',
    CAP_FILE: '470991fbdf7ef586d8cb844aa9792b7f091ecd5f26c748848b1a04362010d434',
}
TRANSIENT_ATTEMPTS = 4
TRANSIENT_SLEEP_S = 900


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def free_gib():
    return shutil.disk_usage('C:/').free/2**30


def chunk_files(root=None):
    """(key or None, path, size) of every chunk file under the L2 tree (z/y/x; '.tmp<pid>' leftovers have key None).
    Only numeric folders are walked, so .zarray, .zattrs and .locks are never listed."""
    root = Path(root or CT_ROOT)
    for z in os.scandir(root):
        if not (z.is_dir() and z.name.isdigit()):
            continue
        for y in os.scandir(z.path):
            if not (y.is_dir() and y.name.isdigit()):
                continue
            for x in os.scandir(y.path):
                if not x.is_file():
                    continue
                if x.name.isdigit():
                    yield (int(z.name), int(y.name), int(x.name)), x.path, x.stat().st_size
                elif x.name.split('.tmp')[0].isdigit() and '.tmp' in x.name:
                    yield None, x.path, x.stat().st_size


def free_ct(keep, root=None):
    """Delete every chunk of this volume's L2 cache not in ``keep``. Returns (deleted, bytes, kept)."""
    root = Path(root or CT_ROOT)
    if 'PHerc0139' not in root.as_posix() or root.name != '2':
        raise RuntimeError(f'free_ct refuses {root}')
    n, size, kept = 0, 0, 0
    for key, path, sz in list(chunk_files(root)):
        if key is not None and key in keep:
            kept += 1
            continue
        try:
            os.unlink(path)
        except OSError:
            continue
        n += 1
        size += sz
    return n, size, kept


def done_rc(path):
    """rc from a DONE-style file ('rc=N ...'), or None when it does not exist or cannot be read."""
    try:
        return int(Path(path).read_text().split()[0].split('=')[1])
    except (OSError, IndexError, ValueError):
        return None


def write_atomic(path, text):
    path = Path(path)
    tmp = path.with_name(path.name+'.tmp')
    for _ in range(5):
        try:
            tmp.write_text(text, encoding='utf-8')
            os.replace(tmp, path)
            return
        except OSError:
            time.sleep(2)


class Fatal(Exception):
    def __init__(self, rc, msg):
        super().__init__(msg)
        self.rc = rc


class Chain:
    def __init__(self, a):
        self.a = a
        self.root = Path(a.root)
        self.bands = json.loads(Path(a.bands_file or self.root/'bands.json').read_text())['bands']
        self.state = dict(stage='start', pid=os.getpid(), started=time.strftime('%Y-%m-%d %H:%M:%S'), band=None, bands={},
                          child=None, c_free_min_gib=None)
        self.rc = 0
        self.lock_path = self.root/'chain.lock.json'

    # ---- housekeeping ----------------------------------------------------------------------------------------
    def log(self, msg):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)
        for _ in range(5):
            try:
                with open(self.root/'chain.log', 'a', encoding='utf-8') as fh:
                    fh.write(line+'\n')
                return
            except OSError:
                time.sleep(1)

    def save(self):
        free = round(free_gib(), 2)
        self.state['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self.state['c_free_gib'] = free
        low = self.state['c_free_min_gib']
        self.state['c_free_min_gib'] = free if low is None else min(low, free)
        write_atomic(self.root/'chain_status.json', json.dumps(self.state, indent=1))

    def env(self):
        e = dict(os.environ)
        e.update(CUDA_VISIBLE_DEVICES='-1', HF_HOME=str(STRIPS/'hf_home'), HF_HUB_OFFLINE='1',
                 OMP_NUM_THREADS=str(THREADS), MKL_NUM_THREADS=str(THREADS), OPENBLAS_NUM_THREADS=str(THREADS),
                 PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
        return e

    def write_lock(self, child=None):
        me = psutil.Process()
        info = dict(pid=me.pid, create_time=me.create_time(), child=None)
        if child is not None:
            info['child'] = dict(pid=child.pid, create_time=psutil.Process(child.pid).create_time())
        write_atomic(self.lock_path, json.dumps(info))

    def check_lock(self):
        """Refuse to start beside a live chain or runner of an earlier launch (PID and create time, not command text)."""
        try:
            info = json.loads(self.lock_path.read_text())
        except (OSError, ValueError):
            return
        for who in (info, info.get('child')):
            if not who:
                continue
            try:
                if psutil.Process(who['pid']).create_time() == who['create_time'] and who['pid'] != os.getpid():
                    raise Fatal(7, f"PID {who['pid']} of an earlier launch is alive ({self.lock_path}); not starting")
            except psutil.Error:
                pass

    def spawn(self, args, out, cwd, band=None):
        """One child at a time: BelowNormal, CREATE_NO_WINDOW, CUDA hidden; its stdout+stderr appended to ``out``."""
        with open(out, 'a', encoding='utf-8') as fo:
            fo.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(map(str, args))}\n")
            fo.flush()
            p = subprocess.Popen([PY, '-I', '-B', '-u']+[str(x) for x in args], cwd=str(cwd), env=self.env(), stdout=fo,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW)
            try:
                self.write_lock(p)
            except psutil.Error:
                pass
            self.state['child'] = dict(pid=p.pid, args=' '.join(map(str, args[:1])))
            self.save()
            while True:
                try:
                    rc = p.wait(timeout=60)
                    break
                except subprocess.TimeoutExpired:
                    self.save()
            self.state['child'] = None
            self.write_lock()
            self.save()
            return rc

    # ---- plan ------------------------------------------------------------------------------------------------
    def plan_dir(self, b):
        return self.root/b['name']/'plan'

    def plan_band(self, b):
        pd = self.plan_dir(b)
        if (pd/'PLAN_OK').exists():
            return
        pd.mkdir(parents=True, exist_ok=True)
        plan = pd/'band_plan.json'
        self.state['stage'] = f"plan {b['name']}"
        self.save()
        rc = None
        for attempt in range(1, TRANSIENT_ATTEMPTS+1):
            rc = self.spawn([TOOLS/'plan_band.py', '--out', plan, '--z0', b['z0'], '--z1', b['z1'], '--band', b['z0'], b['z1'],
                             '--min-arc-sv', MIN_ARC_SV], pd/'log_plan.txt', SCORE)
            if rc == 0:
                rc = self.spawn([SCORE/'tools'/'make_piece_afv.py', plan, FIBERS, pd/'band.afv', '--volume', HTTPS_VOL,
                                 '--base-shape', *BASE_SHAPE, '--full-afv', FULL_AFV, '--map', pd/'band.tsv',
                                 '--runplan', pd/'runplan_band.tsv', '--report', pd/'band_afv_report.json'],
                                pd/'log_afv_band.txt', SCORE)
            if rc == 0:
                break
            self.log(f"{b['name']}: plan attempt {attempt}: rc {rc}")
            if attempt < TRANSIENT_ATTEMPTS:
                time.sleep(120)
        if rc != 0:
            raise Fatal(10, f"{b['name']}: planning failed (rc {rc})")
        summary = self.check_plan(b)
        write_atomic(pd/'plan_summary.json', json.dumps(summary, indent=1))
        write_atomic(pd/'PLAN_OK', json.dumps({k: summary[k] for k in ('files_sha256',)}, indent=1))
        self.log(f"{b['name']}: planned: {summary['pieces']} pieces, {summary['decisions']} decisions, "
                 f"{summary['ct_chunks']} chunks, floor skipped {summary['skipped_under_floor']}")

    def check_plan(self, b):
        """The run plan against the plan and the floor; the provenance record of the band."""
        pd = self.plan_dir(b)
        plan = json.loads((pd/'band_plan.json').read_text())
        with open(pd/'runplan_band.tsv') as fh:
            head = fh.readline().rstrip('\n').split('\t')
            rows = [dict(zip(head, line.rstrip('\n').split('\t'))) for line in fh]
        spans = [float(r['arc_end_patch_vox'])-float(r['arc_start_patch_vox']) for r in rows]
        if rows and min(spans) < MIN_ARC_SV:
            raise Fatal(10, f"{b['name']}: run plan has a span {min(spans)} under the floor")
        if len(rows) != len(plan['pieces']):
            raise Fatal(10, f"{b['name']}: run plan {len(rows)} rows, plan {len(plan['pieces'])} pieces")
        dec = sum(int(r['decisions']) for r in rows)
        if dec != sum(p['decisions'] for p in plan['pieces']):
            raise Fatal(10, f"{b['name']}: run plan decisions differ from the plan")
        union = json.loads((pd/'ct_union.json').read_text())
        if len(union['chunks']) != plan['plan']['ct_chunks_union']:
            raise Fatal(10, f"{b['name']}: ct_union.json differs from the plan")
        files = {f: sha256(pd/f) for f in ('band_plan.json', 'band.afv', 'runplan_band.tsv', 'band.tsv', 'ct_union.json',
                                           'band_afv_report.json')}
        report = json.loads((pd/'band_afv_report.json').read_text())
        return dict(window_l2_z=[b['z0'], b['z1']], clip='[z0, z1) in strips2patches --z-clip', pieces=len(rows),
                    decisions=dec, fibers=plan['plan']['run_stretches']['fibers'],
                    fibers_touching=plan['plan']['run_stretches']['fibers_touching'],
                    by_family=plan['plan']['run_stretches']['by_family'],
                    windows=plan['plan']['run_stretches']['stretches'],
                    ct_chunks=len(union['chunks']), ct_gib=round(len(union['chunks'])*union['chunk_bytes']/2**30, 3),
                    ct_cached_at_plan=union['cached_at_plan'], cpu_hours_range=plan['plan']['run']['cpu_hours_range'],
                    skipped_under_floor=plan['skipped_under_floor']['count'],
                    skipped_pieces=plan['skipped_under_floor']['pieces'],
                    max_head_dev_sv=report['max_head_dev_sv_vs_full_run'],
                    pieces_head_dev_over_1sv=report['pieces_head_dev_over_1sv'],
                    kink_repaired_pieces=report['kink_repaired_pieces'],
                    planner_sha256=sha256(TOOLS/'plan_band.py'), scorer_sha256=plan['provenance']['scorer_sha256'],
                    make_piece_afv_sha256=PINS[SCORE/'tools'/'make_piece_afv.py'], files_sha256=files,
                    written=time.strftime('%Y-%m-%d %H:%M:%S'))

    def union(self, b):
        d = json.loads((self.plan_dir(b)/'ct_union.json').read_text())
        return {tuple(k) for k in d['chunks']}, d['chunk_bytes']

    def budget(self):
        """Per band now: chunks in the plan, on disk, to fetch."""
        have = {k for k, _, _ in chunk_files() if k is not None}
        out = []
        for b in self.bands:
            u, cb = self.union(b)
            s = json.loads((self.plan_dir(b)/'plan_summary.json').read_text())
            out.append(dict(band=b['name'], window=[b['z0'], b['z1']], pieces=s['pieces'], decisions=s['decisions'],
                            fibers=s['fibers'], floor_skipped=s['skipped_under_floor'], chunks=len(u),
                            gib=round(len(u)*cb/2**30, 2), on_disk=len(u & have), to_fetch=len(u-have),
                            fetch_gib=round(len(u-have)*cb/2**30, 2)))
        allu = set().union(*[self.union(b)[0] for b in self.bands])
        extra = have-allu
        return dict(bands=out, cached_0139_chunks=len(have), cached_in_no_band=len(extra),
                    cached_in_no_band_gib=round(len(extra)*2**21/2**30, 2), c_free_gib=round(free_gib(), 2))

    # ---- one band --------------------------------------------------------------------------------------------
    def later_unfinished(self, b):
        names = [x['name'] for x in self.bands]
        keep = set()
        for x in self.bands[names.index(b['name'])+1:]:
            if done_rc(self.root/x['name']/'DONE') not in (0, 1) and (self.plan_dir(x)/'PLAN_OK').exists():
                keep |= self.union(x)[0]
        return keep

    def make_room(self, b):
        """Before a band: when its CT would take C: under the guard + 2 GiB, delete cached chunks no remaining band needs."""
        u, cb = self.union(b)
        have = {k for k, _, _ in chunk_files() if k is not None}
        need = len(u-have)*cb/2**30
        free = free_gib()
        margin = free-need-MIN_FREE_GIB
        self.log(f"{b['name']}: CT {len(u)} chunks, {len(u & have)} cached, {need:.2f} GiB to fetch at most; C: {free:.2f} GiB "
                 f'free, margin over the {MIN_FREE_GIB:g} GiB guard {margin:.2f} GiB')
        if margin >= 2 or self.a.no_free:
            return
        n, size, kept = free_ct(u | self.later_unfinished(b))
        self.log(f"{b['name']}: made room: deleted {n} cached PHerc0139 chunks no remaining band needs ({size/2**30:.2f} "
                 f'GiB), kept {kept}; C: {free_gib():.2f} GiB free')
        margin = free_gib()-need-MIN_FREE_GIB
        if margin < 0:
            self.log(f"{b['name']}: WARNING: CT exceeds the room by {-margin:.2f} GiB: the prefetch will pause at the guard and "
                     'finished pieces\' chunks will be deleted as the band runs (the floor holds; slower)')

    def run_band(self, b):
        bd = self.root/b['name']
        rc = done_rc(bd/'INFER_DONE')
        if rc in (0,) or (rc == 1 and not self.a.retry_failed):
            self.log(f"{b['name']}: inference already finished (rc {rc})")
            return rc
        pd = self.plan_dir(b)
        self.state['stage'] = f"infer {b['name']}"
        self.save()
        extra = shlex.split(self.a.run_band_extra) if self.a.run_band_extra else []
        for attempt in range(1, TRANSIENT_ATTEMPTS+1):
            t0 = time.time()
            rc = self.spawn([TOOLS/'run_band.py', '--plan', pd/'band_plan.json', '--runplan', pd/'runplan_band.tsv', '--afv',
                             pd/'band.afv', '--root', bd, '--done-name', 'INFER_DONE', '--min-free-gib', MIN_FREE_GIB,
                             '--hard-floor-gib', HARD_FLOOR_GIB, '--workers', 2, '--threads', THREADS, '--affinity', CORES,
                             *extra], bd/'runner_stdout.log', SCORE)
            self.log(f"{b['name']}: runner attempt {attempt}: rc {rc}, {(time.time()-t0)/3600:.2f} h")
            if rc in (0, 1, 2, 3, 5):
                return rc
            if attempt < TRANSIENT_ATTEMPTS:    # rc 10 or a killed runner: S3 metadata, a crash; resume-safe
                time.sleep(TRANSIENT_SLEEP_S)
        return 10 if rc == 10 else 11

    def convert(self, b):
        bd = self.root/b['name']
        self.state['stage'] = f"convert {b['name']}"
        self.save()
        if not (bd/'strips').is_dir():
            self.log(f"{b['name']}: no strips folder; nothing to convert")
            write_atomic(bd/'CONVERT_DONE', 'rc=6 no strips folder\n')
            return 6
        rc = self.spawn([TOOLS/'strips2patches.py', 'convert', '--strips', bd/'strips', '--out', bd/'patches', '--plan',
                         self.plan_dir(b)/'band_plan.json', '--cap-file', CAP_FILE, '--min-area-cm2', MIN_AREA_CM2,
                         '--z-clip', b['z0'], b['z1'], '--clean'], bd/'convert.log', SCORE)
        write_atomic(bd/'CONVERT_DONE', f"rc={rc} finished={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        return rc

    def do_band(self, b):
        name = b['name']
        bd = self.root/name
        bd.mkdir(parents=True, exist_ok=True)
        rc = done_rc(bd/'DONE')
        if rc == 0 or (rc == 1 and not self.a.retry_failed):
            self.log(f'{name}: DONE already (rc {rc}), skipped')
            self.state['bands'][name] = dict(rc=rc, skipped=True)
            if not (bd/'CT_FREED').exists():
                self.free_band(b)
            return rc
        if (bd/'DONE').exists():
            os.replace(bd/'DONE', bd/('DONE.prev_'+time.strftime('%Y%m%d_%H%M%S')))
        if (bd/'CT_FREED').exists():
            (bd/'CT_FREED').unlink()
        self.state['band'] = name
        self.make_room(b)
        infer_rc = self.run_band(b)
        if infer_rc in (2, 5):
            convert_rc = None
        else:
            convert_rc = self.convert(b)
        st = {}
        try:
            st = json.loads((bd/'status.json').read_text())
        except (OSError, ValueError):
            pass
        pieces = st.get('pieces', {})
        patches = area = None
        try:
            m = json.loads((bd/'patches'/'manifest.json').read_text())
            patches, area = m['patches_written'], round(m['total_area_cm2'], 3)
        except (OSError, ValueError, KeyError):
            pass
        rc = infer_rc if infer_rc else (20 if convert_rc else 0)
        line = (f"rc={rc} infer_rc={infer_rc} convert_rc={convert_rc} window={b['z0']},{b['z1']} pieces_ok={pieces.get('ok')} "
                f"pieces_skipped_done={pieces.get('skipped')} failed={pieces.get('failed_pieces')} "
                f"skipped_disk={pieces.get('skipped_disk_pieces')} patches={patches} area_cm2={area} "
                f"finished={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        write_atomic(bd/'DONE', line)
        self.log(f'{name}: DONE {line.strip()}')
        self.state['bands'][name] = dict(rc=rc, infer_rc=infer_rc, convert_rc=convert_rc, patches=patches, area_cm2=area,
                                         failed=pieces.get('failed_pieces'), skipped_disk=pieces.get('skipped_disk_pieces'))
        self.save()
        self.free_band(b)
        if infer_rc in (2, 5):
            raise Fatal(infer_rc, f'{name}: runner rc {infer_rc}; the rest of the chain would fail the same way')
        return rc

    def free_band(self, b):
        bd = self.root/b['name']
        if self.a.no_free:
            self.log(f"{b['name']}: --no-free: CT kept")
            return
        before = free_gib()
        n, size, kept = free_ct(self.later_unfinished(b))
        write_atomic(bd/'CT_FREED', f"deleted={n} gib={size/2**30:.3f} kept_for_later_bands={kept} "
                                    f"finished={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.log(f"{b['name']}: CT freed: {n} chunks, {size/2**30:.2f} GiB, {kept} kept for later bands; C: {before:.2f} -> "
                 f'{free_gib():.2f} GiB free')

    # ---- the chain -------------------------------------------------------------------------------------------
    def pins(self):
        bad = [f'{p}: {sha256(p)} != {want}' for p, want in PINS.items() if sha256(p) != want]
        if bad:
            raise Fatal(5, 'pinned file differs: '+'; '.join(bad))
        self.log('pins ok: '+', '.join(f'{p.name} {want[:12]}' for p, want in PINS.items()))
        self.log('tools: '+', '.join(f'{f} {sha256(TOOLS/f)[:12]}' for f in ('plan_band.py', 'run_band.py', 'chain.py')))

    def main(self):
        finish = True
        try:
            me = psutil.Process()
            me.cpu_affinity(list(range(CORES)))
            me.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
            self.check_lock()
            self.write_lock()
            if (self.root/'CHAIN_DONE').exists() and not (self.a.plan_only or self.a.budget):
                os.replace(self.root/'CHAIN_DONE', self.root/('CHAIN_DONE.prev_'+time.strftime('%Y%m%d_%H%M%S')))
            self.log(f'START chain pid {me.pid}, BelowNormal, affinity {me.cpu_affinity()}, CUDA_VISIBLE_DEVICES=-1, '
                     f'C: {free_gib():.2f} GiB free, guard {MIN_FREE_GIB:g}, hard floor {HARD_FLOOR_GIB:g}; '
                     f"bands {[(b['name'], b['z0'], b['z1']) for b in self.bands]}")
            self.pins()
            for b in self.bands:
                self.plan_band(b)
            if self.a.budget:
                finish = False
                print(json.dumps(self.budget(), indent=1))
                return 0
            if self.a.plan_only:
                finish = False
                self.log('--plan-only: finished')
                return 0
            for b in self.bands:
                self.rc = max(self.rc, self.do_band(b))
            self.state['stage'] = 'finished'
        except Fatal as error:
            self.rc = max(self.rc, error.rc)
            self.state['stage'] = f"failed: {self.state['stage']}"
            self.state['error'] = str(error)
            self.log(f'ERROR (rc {error.rc}): {error}')
        except Exception as error:  # noqa: BLE001
            self.rc = max(self.rc, 10)
            self.state['stage'] = f"failed: {self.state['stage']}"
            self.state['error'] = f'{type(error).__name__}: {error}'
            self.log(f'ERROR (rc 10): {type(error).__name__}: {error}')
        finally:
            self.state['rc'] = self.rc
            self.save()
            refused = isinstance(self.state.get('error'), str) and 'of an earlier launch is alive' in self.state['error']
            if finish and not refused:
                bands = ' '.join(f"{n}:rc{v.get('rc')}" for n, v in self.state['bands'].items())
                write_atomic(self.root/'CHAIN_DONE', f"rc={self.rc} stage={self.state['stage']} {bands} "
                                                     f"c_free_min_gib={self.state['c_free_min_gib']} "
                                                     f"finished={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                self.log(f'CHAIN_DONE rc {self.rc}')
            if not refused:
                try:
                    self.lock_path.unlink()
                except OSError:
                    pass
        return self.rc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=str(TOOLS.parent))
    ap.add_argument('--bands-file', default=None)
    ap.add_argument('--plan-only', action='store_true')
    ap.add_argument('--budget', action='store_true', help='print the per-band CT budget now and exit')
    ap.add_argument('--retry-failed', action='store_true', help='also rerun bands whose DONE says rc 1')
    ap.add_argument('--no-free', action='store_true', help='smoke test: delete no CT')
    ap.add_argument('--run-band-extra', default=None, help='smoke test: extra run_band.py arguments')
    sys.exit(Chain(ap.parse_args()).main())


if __name__ == '__main__':
    main()
