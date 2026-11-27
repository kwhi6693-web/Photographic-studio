#!/usr/bin/env python3
"""Photographic Studio v1.6.3 - look route: every output pixel is the ORIGINAL's, re-toned with G's light and colour
(look_transfer.py), then the brief's crop and highlight trim. Nothing G drew reaches the photo.
Used by pipeline.py --g-direct, never by hand:
  * straight after G draw 1 when the original is very dark (median L* < 15 and more than 60 % of the frame below
    L* 20 - the same test as quick_n.py's underexposed branch) or the keep boxes cover more than 40 % of the frame
    (an exhibit that fills the picture: G direct would paste most of it back anyway);
  * when G direct fails for good (draw 2, or any other hard failure), before quick N.
2026-11-26 regression (photos 02 glass sunflower, 03 lantern eaves; both G draws rejected): this route beat the quick N
that was delivered on both; the sentinels on its output read 1.02-1.17 (G direct drafts 1.59-1.66 texture, 2.40-4.04
dark detail). With two G drafts it uses the one whose own texture sentinel is lower.
Dark floor: look_transfer may deepen a hazy backlit frame a lot (03: median L* 7.2 -> 3.1, the lattice sank into
black). The result's median L* is kept at no less than DARK_FLOOR of the original's by blending L* back towards the
look result's own (deepened) value only as far as needed; colour stays G's.
Pure numpy + Pillow apart from look_transfer.py itself (OpenCV or the cvlite stand-in). About 5-12 s.
"""
import tempfile
from pathlib import Path
import numpy as np

from ps_common import load_rgb, save_png, srgb_to_lab, lin_to_lab, lab_to_lin, to_linear, to_srgb
from pipeline import reframe_args, tool

DARK_MEDIAN, DARK_L, DARK_SHARE = 15.0, 20.0, 0.60
KEEP_AREA_MAX = 0.40
DARK_FLOOR = 0.55


def keep_area(regions, shape=(200, 200)):
    """Union of the keep boxes as a share of the frame (boxes in 0-1 fractions)."""
    h, w = shape
    mask = np.zeros(shape, bool)
    for region in regions or []:
        x0, y0, x1, y1 = region['box']
        mask[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))] = True
    return float(mask.mean())


def triggers(source, regions):
    """Which straight-to-look rule applies to this original (computed, never judged by eye)."""
    L = srgb_to_lab(load_rgb(source))[..., 0]
    median, share = float(np.median(L)), float((L < DARK_L).mean())
    area = keep_area(regions)
    dark = median < DARK_MEDIAN and share > DARK_SHARE
    return {'median_L': round(median, 1), 'dark_share': round(share, 2), 'keep_area': round(area, 2),
            'very_dark': dark, 'large_keep': area > KEEP_AREA_MAX,
            'straight_to_look': dark or area > KEEP_AREA_MAX}


def dark_floor(original, result):
    """Lift L* back towards the original only as far as needed to keep the median >= DARK_FLOOR x original's."""
    lab_o, lab_r = lin_to_lab(to_linear(original)), lin_to_lab(to_linear(result))
    med_o, med_r = float(np.median(lab_o[..., 0])), float(np.median(lab_r[..., 0]))
    floor = DARK_FLOOR * med_o
    info = {'median_original': round(med_o, 1), 'median_look': round(med_r, 1), 'floor': round(floor, 1), 'blend': 0.0}
    if med_r >= floor:
        return result, info
    lo, hi = 0.0, 1.0
    for _ in range(20):
        a = (lo + hi) / 2
        if np.median(lab_r[..., 0] + a * (lab_o[..., 0] - lab_r[..., 0])) < floor:
            lo = a
        else:
            hi = a
    lab = lab_r.copy()
    lab[..., 0] = lab_r[..., 0] + hi * (lab_o[..., 0] - lab_r[..., 0])
    info.update(blend=round(hi, 3), median_after=round(float(np.median(lab[..., 0])), 1))
    return np.clip(to_srgb(lab_to_lin(lab)), 0, 1), info


def pick(source, drafts):
    """Of the G drafts, the one whose own texture sentinel is lowest (aligned the way g_first.py aligns)."""
    if len(drafts) == 1:
        return drafts[0], []
    import sentinel
    from g_first import align_g
    original = load_rgb(source)
    scores = []
    for path in drafts:
        try:
            aligned, report = align_g(original, load_rgb(path))
            coverage = report.pop('_coverage', None)
            s = sentinel.measure(original, aligned, coverage) if aligned is not None else None
            scores.append({'g': Path(path).name, 'texture_ratio': s and s['texture_ratio'],
                           'dark_detail_ratio': s and s['dark_detail_ratio']})
        except Exception as error:
            scores.append({'g': Path(path).name, 'error': str(error)})
    usable = [(d, s) for d, s in zip(drafts, scores) if s.get('texture_ratio') is not None]
    if not usable:
        return drafts[-1], scores
    return min(usable, key=lambda item: item[1]['texture_ratio'])[0], scores


def run(source, drafts, params, output, reason):
    steps = {'reason': reason, 'drafts': [Path(d).name for d in drafts]}
    chosen, scores = pick(source, drafts)
    steps['draft_scores'] = scores
    steps['g_used'] = Path(chosen).name
    with tempfile.TemporaryDirectory() as folder_name:
        folder = Path(folder_name)
        looked = folder / 'look.png'
        report = tool('look_transfer.py', source, chosen, looked, folder / 'look.json')
        steps['look_transfer'] = {'verdict': report.get('verdict'), 'flags': report.get('flags', [])}
        if not str(report.get('verdict', '')).startswith('DONE') or not looked.exists():
            steps['verdict'] = 'FAILED: ' + str(report.get('verdict'))
            return steps
        original = load_rgb(source)
        floored, steps['dark_floor'] = dark_floor(original, load_rgb(looked))
        current, source_grid = folder / 'floored.png', folder / 'source.png'
        save_png(floored, current)
        save_png(original, source_grid)
        geometry = reframe_args(params.get('reframe') or {})
        if geometry:
            framed = folder / 'framed.png'
            frame = tool('reframe.py', current, framed, *geometry)
            ok = framed.exists() and frame.get('output_size')
            steps['reframe'] = {'verdict': 'REFRAMED' if ok else 'FAILED', 'args': geometry,
                                'area_retained': frame.get('area_retained')}
            if ok:
                current = framed
        else:
            steps['reframe'] = {'verdict': 'NO_REFRAME'}
        trimmed = folder / 'trimmed.png'
        trim = tool('n_trim.py', current, trimmed)
        steps['n_trim'] = {'verdict': trim.get('verdict')}
        if str(trim.get('verdict', '')).startswith('PASS') and trimmed.exists():
            current = trimmed
        save_png(load_rgb(current), output)
    steps['verdict'] = 'DELIVER_LOOK'
    return steps


if __name__ == '__main__':
    raise SystemExit(__doc__)
