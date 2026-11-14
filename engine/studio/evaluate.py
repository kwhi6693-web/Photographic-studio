"""Evaluation harness: run a fixed photo set several times and summarise what matters for "stable enough for an app".

    python -m studio eval PHOTO_DIR OUT_DIR [--runs=2]

Per photo: route, seconds, model calls, cost estimate, final checks, and run-to-run difference (mean |ΔRGB| of the
finals, 0-255). Writes OUT_DIR/summary.json, OUT_DIR/summary.md and OUT_DIR/sheets/<photo>.jpg
(original | run 1 | run 2 ...), which is what the user scores: is every run of this photo one they are happy with?
"""
import json, statistics
from pathlib import Path
from .pipeline import run

EXT = ('.jpg', '.jpeg', '.png', '.heic', '.tif', '.tiff')


def photos_in(d):
    d = Path(d)
    if (d / 'original.jpeg').exists() or list(d.glob('original.*')):   # a single recorded folder (replay)
        return [next(d.glob('original.*'))]
    out = []
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in EXT: out.append(p)
        elif p.is_dir() and list(p.glob('original.*')): out.append(next(p.glob('original.*')))
    return out


def _diff(a, b):
    import numpy as np
    from PIL import Image
    A = np.asarray(Image.open(a).convert('RGB'), float); im = Image.open(b).convert('RGB')
    if im.size != (A.shape[1], A.shape[0]): im = im.resize((A.shape[1], A.shape[0]))
    return round(float(np.abs(A - np.asarray(im, float)).mean()), 2)


def _sheet(original, finals, out):
    from PIL import Image, ImageOps
    ims = [ImageOps.exif_transpose(Image.open(original)).convert('RGB')] + [Image.open(f).convert('RGB') for f in finals]
    H = 900; ims = [i.resize((round(i.width * H / i.height), H)) for i in ims]
    s = Image.new('RGB', (sum(i.width for i in ims) + 16 * (len(ims) - 1), H), 'white'); x = 0
    for i in ims: s.paste(i, (x, 0)); x += i.width + 16
    out.parent.mkdir(parents=True, exist_ok=True); s.save(out, quality=88)


def evaluate(photo_dir, out_dir, runs=2, cfg=None):
    out = Path(out_dir); rows = []
    for p in photos_in(photo_dir):
        name = p.parent.name if p.stem == 'original' else p.stem
        recs = [run(p, out / f'run{k}' / name, cfg) for k in range(1, runs + 1)]
        finals = [out / f'run{k}' / name / 'final.png' for k in range(1, runs + 1)]
        ok = [f for f in finals if f.exists()]
        row = {'photo': name, 'results': [r.get('result') for r in recs], 'routes': [r.get('route') for r in recs],
               'seconds': [r.get('seconds') for r in recs], 'image_calls': [r['calls']['image'] for r in recs],
               'cost_usd': round(sum(r.get('cost_usd_estimate', 0) for r in recs), 4),
               'final': [r.get('final') for r in recs]}
        if len(ok) >= 2: row['run_to_run_diff'] = max(_diff(ok[0], f) for f in ok[1:])
        if ok: _sheet(p, ok, out / 'sheets' / f'{name}.jpg')
        rows.append(row)
    secs = [s for r in rows for s in r['seconds'] if s]
    summary = {'photos': len(rows), 'runs': runs, 'rows': rows,
               'delivered': sum(x == 'DELIVERED' for r in rows for x in r['results']),
               'median_seconds': statistics.median(secs) if secs else None,
               'g_rejected_runs': sum(str(x).startswith('n_direct') for r in rows for x in r['routes']),
               'cost_usd_total': round(sum(r['cost_usd'] for r in rows), 4),
               'run_to_run_diff_max': max((r.get('run_to_run_diff', 0) for r in rows), default=None)}
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    lines = ['| 照片 | 路线 | 秒 | G 次数 | 两次差别 | 成片检查 |', '|---|---|---|---|---|---|']
    for r in rows:
        lines.append(f"| {r['photo']} | {' / '.join(map(str, r['routes']))} | {' / '.join(map(str, r['seconds']))} | "
                     f"{' / '.join(map(str, r['image_calls']))} | {r.get('run_to_run_diff', '-')} | "
                     f"{' / '.join(str((f or {}).get('intensity', '-'))[:20] for f in r['final'])} |")
    (out / 'summary.md').write_text(
        f"# 评测汇总\n\n{summary['photos']} 张 × {runs} 次；交付 {summary['delivered']}；中位耗时 {summary['median_seconds']} 秒；"
        f"G 被拦下 {summary['g_rejected_runs']} 次；估算成本 {summary['cost_usd_total']} 美元；两次最大差别 {summary['run_to_run_diff_max']}\n\n"
        + '\n'.join(lines) + '\n\n对比图在 sheets/：每张是 原片 | 第 1 次 | 第 2 次。打分只回答：每一次你都满意吗？\n', encoding='utf-8')
    return summary
