"""HTTP service skeleton for the future app: upload a photo, poll, download the result, delete.

    uvicorn service.app:app --app-dir engine          (from the repository root)

POST   /jobs              multipart field "photo"  -> {"id", "status"}
GET    /jobs/{id}         -> {"status": queued|running|done|unsupported|failed, "route", "reason", "seconds"}
GET    /jobs/{id}/result  -> the finished photo (PNG, or JPEG when it was carried back to full resolution)
DELETE /jobs/{id}         -> removes every file of the job
Jobs and files are deleted automatically after STUDIO_TTL_HOURS (default 168 = 7 days).
Single process, in-memory queue: enough for the prototype and tests; production swaps in a real queue and object storage.
No accounts, quotas or payments yet (they belong to the app phase).
"""
from __future__ import annotations

import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from studio_engine import VERSION, Studio, load_config

DATA = Path(os.environ.get('STUDIO_DATA', '/tmp/studio_jobs'))
TTL_S = float(os.environ.get('STUDIO_TTL_HOURS', '168')) * 3600
MAX_BYTES = int(os.environ.get('STUDIO_MAX_MB', '40')) * 1024 * 1024
ALLOWED = ('.jpg', '.jpeg', '.png', '.heic', '.heif')

app = FastAPI(title='Photographic Studio', version=VERSION)
_jobs: dict[str, dict] = {}
_q: queue.Queue = queue.Queue()
_lock = threading.Lock()
studio_factory = lambda: Studio(load_config())   # tests replace this


def _worker():
    while True:
        jid = _q.get()
        job = _jobs.get(jid)
        if not job:
            continue
        job['status'] = 'running'
        try:
            r = studio_factory().run(job['photo'], job['dir'] / 'out')
            job.update(status=r.status, final=r.final, route=r.route, reason=r.reason,
                       seconds=r.receipt.get('seconds_total'))
        except Exception as e:   # never let the worker die
            job.update(status='failed', reason=f'internal error: {e}'[:400])


def _cleanup():
    now = time.time()
    with _lock:
        for jid in [j for j, v in _jobs.items() if now - v['created'] > TTL_S]:
            shutil.rmtree(_jobs[jid]['dir'], ignore_errors=True); _jobs.pop(jid, None)


threading.Thread(target=_worker, daemon=True).start()


@app.post('/jobs')
async def create_job(photo: UploadFile = File(...)):
    _cleanup()
    ext = Path(photo.filename or '').suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(415, f'unsupported file type {ext!r}')
    data = await photo.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, 'file too large')
    jid = uuid.uuid4().hex
    d = DATA / jid; d.mkdir(parents=True, exist_ok=True)
    (d / f'photo{ext}').write_bytes(data)
    with _lock:
        _jobs[jid] = {'status': 'queued', 'dir': d, 'photo': d / f'photo{ext}', 'created': time.time()}
    _q.put(jid)
    return {'id': jid, 'status': 'queued'}


@app.get('/jobs/{jid}')
def job_status(jid: str):
    j = _jobs.get(jid)
    if not j:
        raise HTTPException(404, 'no such job')
    return {k: j.get(k) for k in ('status', 'route', 'reason', 'seconds')}


@app.get('/jobs/{jid}/result')
def job_result(jid: str):
    j = _jobs.get(jid)
    if not j or j.get('status') != 'done' or not j.get('final'):
        raise HTTPException(404, 'no result')
    ext = Path(j['final']).suffix.lower()   # final_full.jpg for photos larger than work_size
    mt = 'image/jpeg' if ext in ('.jpg', '.jpeg') else 'image/png'
    return FileResponse(j['final'], media_type=mt, filename=f'photographic-studio{ext or ".png"}')


@app.delete('/jobs/{jid}')
def job_delete(jid: str):
    with _lock:
        j = _jobs.pop(jid, None)
    if not j:
        raise HTTPException(404, 'no such job')
    shutil.rmtree(j['dir'], ignore_errors=True)
    return {'deleted': jid}
