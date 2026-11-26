"""Batch retouching: many photos in, one finished photo per photo out, and an honest summary.

    python -m studio_engine.cli batch INPUT OUT_DIR [--workers=2] [--config=engine/config.toml]

INPUT is a folder of photos (jpg/jpeg/png/heic/heif) or a single photo.

Why this is a loop of single-photo runs and never one call with several photos (2026-11-26 g-direct batch, v1.4.6):
in a chat host the image model was shown all six originals at once and returned a six-photo grid for photo 02 and an
invented "all six delivered" summary picture for photo 03. Here every photo gets its own `Studio.run`, its own folder
and its own G call carrying only that photo, so one photo can never be drawn into another photo's result.

OUT_DIR/
  <photo>/            the single-photo run: final.png (or final_full.jpg), receipt.json, g*.png, ...
  delivered/<photo>.jpg   only the photos whose status is 'done'
  sheet.jpg           original | final per photo, failed photos marked
  summary.json / summary.md   one row per photo, built only from that photo's own receipt
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .config import load
from .pipeline import Studio

EXTS = ('.jpg', '.jpeg', '.png', '.heic', '.heif')
TARGET_SECONDS = 120   # owner decision 2026-11-14: one photo within 2 minutes


def list_photos(src: str | Path) -> list[Path]:
    p = Path(src)
    if p.is_file():
        return [p]
    return sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() in EXTS and not x.name.startswith('.'))


def _names(photos: list[Path]) -> list[str]:
    """One folder name per photo; same stem with different extensions (a.jpg, a.png) must not share a folder."""
    seen: dict[str, int] = {}
    out = []
    for p in photos:
        n = seen.get(p.stem, 0); seen[p.stem] = n + 1
        out.append(p.stem if n == 0 else f'{p.stem}_{n + 1}')
    return out


def _one(photo: Path, name: str, out: Path, studio_factory) -> dict:
    t0 = time.time()
    row = {'photo': photo.name, 'name': name, 'status': 'failed', 'route': '', 'reason': '', 'final': None,
           'delivered': None, 'seconds': None, 'g_calls': None, 'cost_usd': None}
    try:
        r = studio_factory(photo).run(photo, out / name)
        rc = r.receipt or {}
        row.update(status=r.status, route=r.route, reason=(r.reason or '')[:300], final=r.final,
                   seconds=rc.get('seconds_total'), g_calls=rc.get('g_calls'),
                   cost_usd=rc.get('usage', {}).get('cost_usd_estimate'),
                   physics=str(rc.get('final_physics'))[:80] if rc.get('final_physics') else None)
    except Exception as e:   # one bad photo must not stop the batch
        row['reason'] = f'internal error: {e}'[:300]
    if row['seconds'] is None:
        row['seconds'] = round(time.time() - t0, 1)
    # a photo counts as delivered only when its own run says done and the file is really there
    if row['status'] == 'done' and row['final'] and Path(row['final']).exists():
        d = out / 'delivered' / f'{name}.jpg'
        d.parent.mkdir(parents=True, exist_ok=True)
        Image.open(row['final']).convert('RGB').save(d, 'JPEG', quality=95)
        row['delivered'] = str(d)
    elif row['status'] == 'done':
        row.update(status='failed', reason='run reported done but no final file was found')
    return row


def contact_sheet(rows: list[dict], photos: dict[str, Path], out: Path, height: int = 360):
    lines = []
    for r in rows:
        try:
            a = ImageOps.exif_transpose(Image.open(photos[r['name']])).convert('RGB')
        except Exception:
            a = Image.new('RGB', (480, 360), 'grey')
        b = Image.open(r['final']).convert('RGB') if r.get('delivered') else Image.new('RGB', a.size, (90, 90, 90))
        a, b = [i.resize((max(1, round(i.width * height / i.height)), height)) for i in (a, b)]
        lines.append((r, a, b))
    W = max((a.width + b.width + 16 for _, a, b in lines), default=400) + 20
    H = sum(height + 40 for _ in lines) + 10
    s = Image.new('RGB', (W, max(H, 60)), 'white'); d = ImageDraw.Draw(s); y = 10
    for r, a, b in lines:
        label = f"{r['photo']}  -  {r['status']}" + (f"  ({r['route']})" if r['route'] else f"  {r['reason'][:80]}")
        d.text((10, y), label, fill='black' if r['status'] == 'done' else (180, 0, 0))
        s.paste(a, (10, y + 30)); s.paste(b, (10 + a.width + 16, y + 30))
        if not r.get('delivered'):
            d.text((10 + a.width + 30, y + 30 + height // 2), 'NOT DELIVERED', fill=(255, 200, 200))
        y += height + 40
    s.save(out, quality=90)


def summary_md(rows: list[dict], seconds_wall: float, workers: int) -> str:
    done = [r for r in rows if r['status'] == 'done']
    secs = [r['seconds'] for r in rows if r['seconds'] is not None]
    cost = sum(r['cost_usd'] or 0 for r in rows)
    md = [f'# Batch: {len(done)}/{len(rows)} delivered', '',
          f'- wall time {seconds_wall:.0f} s with {workers} worker(s); per photo median '
          f'{sorted(secs)[len(secs) // 2]:.0f} s, over {TARGET_SECONDS} s: {sum(1 for x in secs if x > TARGET_SECONDS)}/{len(secs)}'
          if secs else '- seconds: n/a',
          f'- estimated cost ${cost:.2f}',
          '- every row comes from that photo\'s own receipt.json; nothing here is filled in by hand', '',
          '| photo | status | route | G calls | seconds | reason |', '|---|---|---|---:|---:|---|']
    for r in rows:
        md.append(f"| {r['photo']} | {r['status']} | {r['route']} | {r['g_calls'] if r['g_calls'] is not None else ''} | "
                  f"{r['seconds']} | {(r['reason'] or '').replace('|', '/')[:120]} |")
    not_done = [r for r in rows if r['status'] != 'done']
    if not_done:
        md += ['', f'Not delivered ({len(not_done)}): ' + ', '.join(r['photo'] for r in not_done) +
               '. Their folders keep the receipt and any G drafts for diagnosis; they are not finished photos.']
    return '\n'.join(md) + '\n'


def run_batch(src: str | Path, out_dir: str | Path, workers: int = 2, config: str | None = None,
              studio_factory=None) -> dict:
    photos = list_photos(src)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    names = _names(photos)
    factory = studio_factory or (lambda p: Studio(load(config)))   # a fresh Studio per photo: no shared state
    workers = max(1, min(int(workers), len(photos) or 1))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(lambda pn: _one(pn[0], pn[1], out, factory), zip(photos, names)))
    wall = round(time.time() - t0, 1)
    res = {'photos': len(rows), 'delivered': sum(1 for r in rows if r['status'] == 'done'),
           'seconds_wall': wall, 'workers': workers, 'rows': rows}
    (out / 'summary.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    (out / 'summary.md').write_text(summary_md(rows, wall, workers), encoding='utf-8')
    if rows:
        contact_sheet(rows, dict(zip(names, photos)), out / 'sheet.jpg')
    return res
