"""HTTP API for the future app (FastAPI). One process, an in-memory job table and a worker thread: enough for the
prototype and for the app's development; swap the queue for a real one (Redis/SQS) before going public.

    uvicorn studio.server:app --port 8000        (from the engine folder)

POST   /jobs              multipart file=<photo>       -> {"id": ..., "status": "queued"}
GET    /jobs/{id}                                      -> status, receipt summary
GET    /jobs/{id}/result                               -> the final PNG
DELETE /jobs/{id}                                      -> deletes the photo, the result and every intermediate file
"""
import os, queue, shutil, threading, time, uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .config import Config
from .pipeline import run

DATA = Path(os.environ.get('STUDIO_DATA', '/tmp/studio-jobs'))
MAX_BYTES = 40 * 1024 * 1024
KEEP_SECONDS = int(os.environ.get('STUDIO_KEEP_SECONDS', str(7 * 24 * 3600)))   # deleted after 7 days by default

app = FastAPI(title='Photographic Studio', version='0.1.0')
JOBS, Q = {}, queue.Queue()


def _worker():
    while True:
        jid = Q.get()
        job = JOBS.get(jid)
        if not job: continue
        job['status'] = 'running'
        try:
            rec = run(job['photo'], job['dir'] / 'out', Config.from_env())
            job['receipt'] = {k: rec.get(k) for k in ('result', 'route', 'seconds', 'final', 'calls')}
            job['status'] = 'done' if rec.get('result') == 'DELIVERED' else 'failed'
        except Exception as e:   # never let one photo stop the worker
            job['status'], job['error'] = 'failed', str(e)[:300]


def _janitor():
    while True:
        now = time.time()
        for jid, job in list(JOBS.items()):
            if now - job['created'] > KEEP_SECONDS: _delete(jid)
        time.sleep(600)


threading.Thread(target=_worker, daemon=True).start()
threading.Thread(target=_janitor, daemon=True).start()


def _delete(jid):
    job = JOBS.pop(jid, None)
    if job: shutil.rmtree(job['dir'], ignore_errors=True)


@app.post('/jobs')
async def create(file: UploadFile = File(...)):
    data = await file.read()
    if not data or len(data) > MAX_BYTES: raise HTTPException(413, 'photo missing or larger than 40 MB')
    jid = uuid.uuid4().hex; d = DATA / jid; d.mkdir(parents=True)
    suffix = Path(file.filename or 'photo.jpg').suffix.lower() or '.jpg'
    photo = d / f'upload{suffix}'; photo.write_bytes(data)
    JOBS[jid] = {'id': jid, 'status': 'queued', 'photo': photo, 'dir': d, 'created': time.time()}
    Q.put(jid)
    return {'id': jid, 'status': 'queued'}


@app.get('/jobs/{jid}')
def status(jid: str):
    job = JOBS.get(jid)
    if not job: raise HTTPException(404, 'no such job')
    return {k: job.get(k) for k in ('id', 'status', 'receipt', 'error')}


@app.get('/jobs/{jid}/result')
def result(jid: str):
    job = JOBS.get(jid)
    if not job: raise HTTPException(404, 'no such job')
    f = job['dir'] / 'out' / 'final.png'
    if job['status'] != 'done' or not f.exists(): raise HTTPException(409, f"not ready: {job['status']}")
    return FileResponse(f, media_type='image/png', filename='photographic-studio.png')


@app.delete('/jobs/{jid}')
def delete(jid: str):
    if jid not in JOBS: raise HTTPException(404, 'no such job')
    _delete(jid); return {'id': jid, 'deleted': True}
