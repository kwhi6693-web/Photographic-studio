"""Evaluation harness: run a fixed set of photos N times each and write one sheet to judge.

    python -m studio_engine.eval EVAL_SET_DIR OUT_DIR [--runs=2] [--config=engine/config.toml]

EVAL_SET_DIR holds the photos (jpg/jpeg/png/heic). For each photo and run the pipeline writes OUT_DIR/<photo>/run<k>/.
Then: OUT_DIR/sheets/<photo>.jpg (original | run1 | run2 ...), OUT_DIR/summary.csv and OUT_DIR/summary.md with
status, route, seconds, estimated cost, final checks and the run-to-run difference (mean |RGB| difference, 0-255).
The user scores the sheets: is every run a photo they would keep? Are the runs equally good?
"""
from __future__ import annotations

import csv
import itertools
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .config import load
from .pipeline import Studio

EXTS = ('.jpg', '.jpeg', '.png', '.heic', '.heif')
TARGET_SECONDS = 120   # owner decision 2026-11-14: one photo within 2 minutes


def _diff(a: str, b: str) -> float:
    A = np.asarray(Image.open(a).convert('RGB'), np.float32)
    B = np.asarray(Image.open(b).convert('RGB').resize((A.shape[1], A.shape[0])), np.float32)
    return round(float(np.abs(A - B).mean()), 2)


def sheet(original: Path, finals: list[str | None], out: Path, height: int = 900):
    ims = [ImageOps.exif_transpose(Image.open(original)).convert('RGB')] + \
          [Image.open(f).convert('RGB') if f else Image.new('RGB', (600, 800), 'grey') for f in finals]
    ims = [i.resize((round(i.width * height / i.height), height)) for i in ims]
    W = sum(i.width for i in ims) + 16 * (len(ims) - 1)
    s = Image.new('RGB', (W, height + 50), 'white'); d = ImageDraw.Draw(s); x = 0
    for lab, im in zip(['original'] + [f'run {k + 1}' for k in range(len(finals))], ims):
        s.paste(im, (x, 50)); d.text((x + 10, 15), lab, fill='black'); x += im.width + 16
    out.parent.mkdir(parents=True, exist_ok=True); s.save(out, quality=90)


def evaluate(set_dir: str, out_dir: str, runs: int = 2, config: str | None = None, studio_factory=None) -> list[dict]:
    photos = sorted(p for p in Path(set_dir).iterdir() if p.suffix.lower() in EXTS)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in photos:
        finals, row = [], {'photo': p.name}
        for k in range(1, runs + 1):
            studio = studio_factory(p) if studio_factory else Studio(load(config))
            r = studio.run(p, out / p.stem / f'run{k}')
            finals.append(r.final)
            rc = r.receipt
            row.update({f'run{k}_status': r.status, f'run{k}_route': r.route, f'run{k}_reason': r.reason[:120],
                        f'run{k}_seconds': rc.get('seconds_total'), f'run{k}_cost_usd': rc.get('usage', {}).get('cost_usd_estimate'),
                        f'run{k}_g_calls': rc.get('g_calls'), f'run{k}_intensity': str(rc.get('final_intensity'))[:60],
                        f'run{k}_physics': str(rc.get('final_physics'))[:40]})
        ok = [f for f in finals if f]
        diffs = [_diff(a, b) for a, b in itertools.combinations(ok, 2)]
        row['run_diff_max'] = max(diffs) if diffs else ''
        sheet(p, finals, out / 'sheets' / f'{p.stem}.jpg')
        rows.append(row)
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k != 'photo', k))
    with open(out / 'summary.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    done = [r for r in rows for k in range(1, runs + 1) if r.get(f'run{k}_status') == 'done']
    secs = [r[f'run{k}_seconds'] for r in rows for k in range(1, runs + 1) if r.get(f'run{k}_seconds')]
    cost = [r[f'run{k}_cost_usd'] or 0 for r in rows for k in range(1, runs + 1)]
    md = [f'# Evaluation: {len(photos)} photos x {runs} runs', '',
          f'- finished: {len(done)}/{len(photos) * runs}',
          (f'- seconds per run: median {np.median(secs):.0f}, max {max(secs):.0f}; over {TARGET_SECONDS} s: '
           f'{sum(1 for x in secs if x > TARGET_SECONDS)}/{len(secs)}') if secs else '- seconds: n/a',
          f'- estimated cost: total ${sum(cost):.2f}, per run ${sum(cost) / max(1, len(cost)):.3f}',
          f'- run-to-run difference (mean |RGB|): ' + ', '.join(f"{r['photo']} {r['run_diff_max']}" for r in rows), '',
          'Score each sheet in sheets/: would you keep every run? Are the runs equally good?']
    (out / 'summary.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    return rows


def main(argv=None):
    a = [x for x in (argv or sys.argv[1:]) if not x.startswith('--')]
    o = dict(x[2:].split('=', 1) for x in (argv or sys.argv[1:]) if x.startswith('--') and '=' in x)
    if len(a) < 2:
        sys.exit(__doc__)
    rows = evaluate(a[0], a[1], int(o.get('runs', 2)), o.get('config'))
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
