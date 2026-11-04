"""November band runner: CT prefetch + strip inference for every piece of the band run plan, CPU only, detached.

    python -I -B -u run_band.py --plan PLAN.json --runplan RUNPLAN.tsv --afv PIECES.afv --root RUN_DIR
        [--min-free-gib 25] [--workers 2] [--threads 8]

Mirrors the frozen October runner (C:/VesuviusTemp/strips/score/runs/v3/run_all.ps1 + prefetch_v3.py), unchanged in
what it runs: one ``infer_cpu.py`` process per piece (the frozen wrapper around villa's sheet_strip/infer.py at
6f2024569 + #2163 + the normalization patch, 8 torch threads, BelowNormal, CUDA hidden, HF offline), with the run
plan's exact ``--arc`` and the frozen arguments (--step 8 --blend 16 --trim 75 --batch 32 --index none --no-render).
Stages (status.json "stage"): verify (FREEZE.txt of the October workspace) -> preflight (model + CT metadata, no
inference) -> run: a prefetch thread (<= --workers HTTPS connections, villa's cache layout, atomic writes, resume-safe,
stops when C: falls below --min-free-gib) walks the pieces in run order while the main thread runs the pieces whose
chunks are all cached, in run order, one at a time; a piece whose chunks cannot be fetched (disk guard) is skipped
and listed. Per piece: records/<piece>.json (by infer_cpu.py), pieces/<piece>.out/.err (villa's stdout), strips/<piece>/
(villa's output). RUN_DIR/status.json is rewritten after every event; RUN_DIR/DONE is written at the end with the rc
(0 all pieces ok; 1 some piece failed; 2 CUDA visible; 3 disk guard skipped pieces; 5 FREEZE mismatch; 10 other).
The runner never reads strip outputs. Resume: run the same command again (finished pieces and cached chunks skipped).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import numpy as np
import psutil
import requests

STRIPS = Path('C:/VesuviusTemp/strips')
SCORE = STRIPS/'score'
sys.path.insert(0, str(SCORE))
import score_strips as S  # noqa: E402

PY = 'C:/Users/PC/miniconda3/envs/vesuvius/python.exe'
BUCKET = 'vesuvius-challenge-open-data'
HTTPS = f'https://{BUCKET}.s3.us-east-1.amazonaws.com'
VOL = 'PHerc0139/volumes/20260102150214-2.399um-0.2m-78keV-masked.zarr'
CT = f's3://{BUCKET}/{VOL}'
UMB = 'C:/VesuviusTemp/strips/data/umbilicus/PHerc0139_20260102150214_umbilicus_L2.json'
CACHE = STRIPS/'ct_cache'
CHECKPOINT = 'scrollprize/fiber_strip_small_v1@7bd163a22c839ff312879ae1916195d0c9729c0e'
SPACE = 'PHerc0139/20260102150214@L0'
INFER_CPU = SCORE/'runs'/'v3'/'infer_cpu.py'
LEVEL = S.CT_LEVEL


class Runner:
    def __init__(self, a):
        self.a = a
        self.root = Path(a.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root/'run.log'
        self.status_path = self.root/'status.json'
        self.done_path = self.root/'DONE'
        self.lock = threading.Lock()
        self.state = dict(stage='start', pid=os.getpid(), started=time.strftime('%Y-%m-%d %H:%M:%S'), rc=None,
                          plan=str(a.plan), runplan=str(a.runplan), afv=str(a.afv), pieces=dict(), prefetch=dict(),
                          current=None)
        self.prefetch_stopped = False     # disk guard tripped
        self.prefetch_done = threading.Event()
        self.cached_pieces = set()        # piece ids whose chunks are all cached (checked by the prefetch thread)
        self.rc = 0

    def log(self, msg):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)
        for _ in range(5):
            try:
                with open(self.log_path, 'a', encoding='utf-8') as fh:
                    fh.write(line+'\n')
                return
            except OSError:
                time.sleep(1)

    def save(self):
        with self.lock:
            self.state['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
            self.state['c_free_gib'] = round(shutil.disk_usage('C:/').free/2**30, 2)
            tmp = self.status_path.with_suffix('.tmp')
            try:
                tmp.write_text(json.dumps(self.state, indent=1))
                os.replace(tmp, self.status_path)
            except OSError:
                pass

    def env(self):
        e = dict(os.environ)
        e.update(CUDA_VISIBLE_DEVICES='-1', HF_HOME=str(STRIPS/'hf_home'), HF_HUB_OFFLINE='1',
                 OMP_NUM_THREADS=str(self.a.threads), MKL_NUM_THREADS=str(self.a.threads),
                 OPENBLAS_NUM_THREADS=str(self.a.threads), PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1',
                 PYTHONDONTWRITEBYTECODE='1')
        return e

    def run_py(self, args, out, err, cwd):
        # CREATE_NO_WINDOW: this runner is detached (no console), so without it Windows allocates a new console
        # window for every child; closing that window sends CTRL_CLOSE and the child dies with 0xC000013A
        # (STATUS_CONTROL_C_EXIT), which is what killed N0002 attempt 1 on 4 Nov at 15:27:45. Append mode keeps
        # every attempt's output.
        with open(out, 'a', encoding='utf-8') as fo, open(err, 'a', encoding='utf-8') as fe:
            fo.write(f"=== attempt at {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"); fo.flush()
            p = subprocess.Popen([PY, '-I', '-B', '-u']+args, cwd=cwd, env=self.env(), stdout=fo, stderr=fe,
                                 stdin=subprocess.DEVNULL,
                                 creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW)
            with self.lock:
                self.state['child_pid'] = p.pid
            return p.wait()

    # ---- stages ----------------------------------------------------------------------------------------------
    def verify(self):
        self.state['stage'] = 'verify'; self.save()
        r = self.run_py([str(SCORE/'tools'/'write_freeze.py'), '--verify'], self.root/'verify.out', self.root/'verify.err', str(SCORE))
        txt = (self.root/'verify.out').read_text(encoding='utf-8', errors='replace').replace('\n', ' ')
        self.log(f'verify FREEZE.txt (October workspace): rc {r}; {txt.strip()}')
        if r != 0:
            self.rc = 5
            raise RuntimeError('FREEZE mismatch: a frozen October file differs')

    def preflight(self):
        self.state['stage'] = 'preflight'; self.save()
        r = self.run_py([str(INFER_CPU), '--preflight', CT, UMB], self.root/'preflight.out', self.root/'preflight.err', str(SCORE))
        txt = (self.root/'preflight.out').read_text(encoding='utf-8', errors='replace').replace('\n', ' ')
        self.log(f'preflight rc {r}: {txt.strip()[:600]}')
        if r == 2:
            self.rc = 2
            raise RuntimeError('torch sees CUDA')
        if r != 0:
            self.rc = 10
            raise RuntimeError(f'preflight failed (rc {r})')

    def load_plan(self):
        plan = json.loads(Path(self.a.plan).read_text())
        pieces = {p['id']: p for p in plan['pieces']}
        with open(self.a.runplan, newline='') as fh:
            rows = [r for r in csv.DictReader(fh, delimiter='\t') if r['run'] == 'True']
        rows.sort(key=lambda r: int(r['run_order']))
        names = {pieces[r['piece']]['fiber'] for r in rows}
        fibers, _ = S.load_fibers(str(SCORE/'data'/'fibers0139'), names=names, space=SPACE)
        by = {f.name: f for f in fibers}
        meta = requests.get(f'{HTTPS}/{VOL}/{LEVEL}/.zarray', timeout=60).json()
        assert meta['compressor'] is None and meta['dtype'] == '|u1' and meta.get('filters') is None, meta
        keys = {}
        for r in rows:
            p = pieces[r['piece']]
            keys[p['id']] = sorted(S.ct_footprint(S.head_path_l0(by[p['fiber']], p['heads_sv']), LEVEL, S.CT_RADIUS,
                                                  meta['chunks'], meta['shape']))
            if len(keys[p['id']]) != p['ct_chunks']:
                raise RuntimeError(f"{p['id']}: {len(keys[p['id']])} chunks, the plan has {p['ct_chunks']}")
        union = set().union(*keys.values())
        want = plan['plan']['ct_chunks_union']
        if len(union) != want:
            raise RuntimeError(f'{len(union)} chunks in the union, the plan has {want}')
        return rows, pieces, keys, meta

    # ---- prefetch thread ---------------------------------------------------------------------------------------
    def prefetch(self, rows, keys, meta):
        a = self.a
        chunks, shape, sep = meta['chunks'], meta['shape'], meta.get('dimension_separator', '.')
        fill = meta.get('fill_value') or 0
        nbytes = int(np.prod(chunks))
        root = CACHE/'s3'/BUCKET/VOL/str(LEVEL)
        if not (root/'.zarray').exists():
            raise RuntimeError(f'{root}/.zarray missing (villa cache metadata)')
        session = requests.Session()
        session.mount('https://', requests.adapters.HTTPAdapter(pool_connections=a.workers, pool_maxsize=a.workers))

        def fetch(k):
            url = f'{HTTPS}/{VOL}/{LEVEL}/{sep.join(map(str, k))}'
            for attempt in range(8):
                try:
                    r = session.get(url, timeout=300)
                    if r.status_code == 404:
                        data = np.full(chunks, fill, np.uint8).tobytes()
                    elif r.status_code == 200 and len(r.content) == nbytes:
                        data = r.content
                    else:
                        raise IOError(f'HTTP {r.status_code}, {len(r.content)} bytes')
                    if any((ki+1)*c > s for ki, c, s in zip(k, chunks, shape)):  # villa pads the clipped edge
                        arr = np.frombuffer(data, np.uint8).reshape(chunks).copy()
                        for ax, (ki, c, s) in enumerate(zip(k, chunks, shape)):
                            if s-ki*c < c:
                                idx = [slice(None)]*3
                                idx[ax] = slice(s-ki*c, None)
                                arr[tuple(idx)] = fill
                        data = arr.tobytes()
                    dest = root/sep.join(map(str, k))
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_name(dest.name+f'.tmp{os.getpid()}')
                    tmp.write_bytes(data)
                    os.replace(tmp, dest)
                    return r.status_code, len(r.content)
                except Exception as error:  # noqa: BLE001
                    if attempt == 7:
                        raise
                    self.log(f'[prefetch] retry {k}: {error}')
                    time.sleep(5*(attempt+1))

        todo_all = {}
        seen = set()
        for r in rows:
            mine = [k for k in keys[r['piece']] if k not in seen and not (root/sep.join(map(str, k))).exists()]
            seen.update(keys[r['piece']])
            todo_all[r['piece']] = mine
        total = sum(len(v) for v in todo_all.values())
        self.log(f'[prefetch] {len(rows)} pieces, {len(seen)} chunks ({len(seen)*nbytes/2**30:.2f} GiB), '
                 f'{len(seen)-total} cached, {total} to fetch ({total*nbytes/2**30:.2f} GiB), {a.workers} connections, '
                 f'disk guard {a.min_free_gib:g} GiB')
        t0, done, got, missing = time.time(), 0, 0, 0
        try:
            with ThreadPoolExecutor(a.workers) as pool:
                for r in rows:
                    todo = todo_all[r['piece']]
                    for i in range(0, len(todo), a.batch):
                        free = shutil.disk_usage('C:/').free/2**30
                        if free < a.min_free_gib:
                            self.log(f'[prefetch] STOP: C: has {free:.2f} GiB free (< {a.min_free_gib:g}); '
                                     f'{done}/{total} fetched; pieces without cached CT will be skipped')
                            self.prefetch_stopped = True
                            return
                        for status, n in pool.map(fetch, todo[i:i+a.batch]):
                            done += 1
                            got += n if status == 200 else 0
                            missing += status == 404
                        el = time.time()-t0
                        with self.lock:
                            self.state['prefetch'] = dict(fetched=done, to_fetch=total, chunks=len(seen),
                                                          mib=round(got/2**20, 1), mib_per_s=round(got/2**20/max(el, 1e-9), 3),
                                                          piece=r['piece'], c_free_gib=round(free, 2),
                                                          updated=time.strftime('%Y-%m-%d %H:%M:%S'))
                        self.save()
                        if done % (a.batch*8) == 0 or done == total:
                            self.log(f'[prefetch] {done}/{total} chunks, {got/2**20:.0f} MiB, {el:.0f} s, '
                                     f'{got/2**20/max(el, 1e-9):.2f} MiB/s, C: {free:.1f} GiB free (piece {r["piece"]})')
                    if all((root/sep.join(map(str, k))).exists() for k in keys[r['piece']]):
                        self.cached_pieces.add(r['piece'])
                    else:
                        self.log(f"[prefetch] {r['piece']}: chunks still missing after fetch")
            self.log(f'[prefetch] done: {done} fetched ({missing} missing objects -> fill), {got/2**20:.0f} MiB in '
                     f'{time.time()-t0:.0f} s')
        except Exception as error:  # noqa: BLE001
            self.log(f'[prefetch] ERROR: {type(error).__name__}: {error}')
            self.prefetch_stopped = True
        finally:
            self.prefetch_done.set()

    # ---- inference -------------------------------------------------------------------------------------------
    def infer(self, rows, pieces, keys, meta):
        a = self.a
        sep = meta.get('dimension_separator', '.')
        root = CACHE/'s3'/BUCKET/VOL/str(LEVEL)
        for d in ('strips', 'records', 'pieces'):
            (self.root/d).mkdir(exist_ok=True)
        st = dict(planned=len(rows), decisions=int(sum(int(r['decisions']) for r in rows)), ok=0, skipped=0, failed=0,
                  skipped_disk=0, failed_pieces=[], skipped_disk_pieces=[], decisions_done=0, infer_seconds=0.)
        self.state['pieces'] = st
        self.state['stage'] = 'run'; self.save()
        self.log(f"infer: {len(rows)} pieces, {st['decisions']} decisions")
        th = threading.Thread(target=self.prefetch, args=(rows, keys, meta), daemon=True)
        th.start()
        pending = list(rows)
        while pending:
            r = pending[0]
            piece = r['piece']
            out, rec = self.root/'strips'/piece, self.root/'records'/f'{piece}.json'
            done = False
            if rec.exists() and (out/'strip.npz').exists() and (out/'strip'/'meta.json').exists():
                try:
                    done = json.loads(rec.read_text()).get('status') == 'ok'
                except Exception:  # noqa: BLE001
                    done = False
            if done:
                st['skipped'] += 1
                st['decisions_done'] += int(r['decisions'])
                self.log(f'infer {piece}: done already, skipped')
                pending.pop(0); self.save()
                continue
            cached = piece in self.cached_pieces or all((root/sep.join(map(str, k))).exists() for k in keys[piece])
            if not cached:
                if self.prefetch_done.is_set():
                    st['skipped_disk'] += 1
                    st['skipped_disk_pieces'].append(piece)
                    self.log(f'infer {piece}: CT not cached and the prefetch has stopped; skipped')
                    pending.pop(0); self.save()
                    continue
                with self.lock:
                    self.state['current'] = f'waiting for CT of {piece}'
                self.save()
                time.sleep(10)
                continue
            args = [str(INFER_CPU), str(rec), '--', '--afv', str(a.afv), '--fiber', r['afv_id'],
                    '--arc', r['arc_start_patch_vox'], r['arc_end_patch_vox'], '--out', str(out),
                    '--checkpoint', CHECKPOINT, '--ct', CT, '--umbilicus', UMB, '--cache-dir', str(CACHE).replace('\\', '/'),
                    '--device', 'cpu', '--index', 'none', '--no-render', '--step', '8', '--blend', '16', '--trim', '75',
                    '--batch', '32']
            rc = 1
            for attempt in (1, 2):
                with self.lock:
                    self.state['current'] = dict(piece=piece, attempt=attempt, decisions=int(r['decisions']),
                                                 started=time.strftime('%Y-%m-%d %H:%M:%S'))
                self.save()
                t0 = time.time()
                rc = self.run_py(args, self.root/'pieces'/f'{piece}.out', self.root/'pieces'/f'{piece}.err', str(SCORE))
                sec = time.time()-t0
                rate = int(r['decisions'])/sec if sec > 0 else 0.
                self.log(f"infer {piece} (attempt {attempt}): rc {rc}, {r['decisions']} decisions, {sec:.1f} s, "
                         f'{rate:.3f} decisions/s incl. start-up')
                if rc == 2:
                    self.rc = 2
                    raise RuntimeError('torch sees CUDA')
                if rc == 0:
                    break
            st['infer_seconds'] += sec
            if rc == 0:
                st['ok'] += 1
                st['decisions_done'] += int(r['decisions'])
            else:
                st['failed'] += 1
                st['failed_pieces'].append(piece)
            pending.pop(0)
            with self.lock:
                self.state['current'] = None
            self.save()
        th.join(timeout=5)
        self.log(f"infer: ok {st['ok']}, skipped (already done) {st['skipped']}, failed {st['failed']}, "
                 f"skipped for disk {st['skipped_disk']}; inference wall {st['infer_seconds']/3600:.2f} h")
        if st['failed']:
            self.rc = max(self.rc, 1)
        if st['skipped_disk']:
            self.rc = max(self.rc, 3)

    def main(self):
        try:
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:  # noqa: BLE001
            pass
        if self.done_path.exists():
            self.done_path.rename(self.root/('DONE.prev_'+time.strftime('%Y%m%d_%H%M%S')))
        self.save()
        try:
            git = subprocess.run(['git', '-C', str(STRIPS/'villa_6f2'), 'rev-parse', 'HEAD'], capture_output=True,
                                 text=True).stdout.strip()
            self.log(f'START band runner pid {os.getpid()} (BelowNormal), CUDA_VISIBLE_DEVICES=-1, HF_HUB_OFFLINE=1, '
                     f"C: {shutil.disk_usage('C:/').free/2**30:.2f} GiB free; villa worktree {STRIPS/'villa_6f2'} at {git} "
                     f'(+ #2163 + normalization patch); checkpoint {CHECKPOINT}; {self.a.threads} torch threads')
            self.verify()
            self.preflight()
            self.state['stage'] = 'load_plan'; self.save()
            rows, pieces, keys, meta = self.load_plan()
            self.log(f'plan: {len(rows)} run pieces; CT chunk union {len(set().union(*keys.values()))} checked against the plan')
            self.infer(rows, pieces, keys, meta)
            self.state['stage'] = 'finished'
        except Exception as error:  # noqa: BLE001
            if self.rc == 0:
                self.rc = 10
            self.state['stage'] = f"failed: {self.state['stage']}"
            self.state['error'] = f'{type(error).__name__}: {error}'
            self.log(f'ERROR (rc {self.rc}): {type(error).__name__}: {error}')
        finally:
            self.state['rc'] = self.rc
            self.save()
            for _ in range(5):
                try:
                    self.done_path.write_text(f"rc={self.rc} stage={self.state['stage']} finished={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    break
                except OSError:
                    time.sleep(2)
            self.log(f'DONE rc {self.rc}')
        return self.rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--runplan', required=True)
    ap.add_argument('--afv', required=True)
    ap.add_argument('--root', required=True)
    ap.add_argument('--min-free-gib', type=float, default=25.)
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--threads', type=int, default=8)
    a = ap.parse_args()
    if a.workers > 2:
        raise SystemExit('at most 2 connections')
    sys.exit(Runner(a).main())


if __name__ == '__main__':
    main()
